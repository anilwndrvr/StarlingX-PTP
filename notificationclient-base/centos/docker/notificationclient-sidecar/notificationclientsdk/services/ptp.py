#
# Copyright (c) 2021 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

import oslo_messaging
import logging
import json
import kombu

from notificationclientsdk.repository.node_repo import NodeRepo
from notificationclientsdk.repository.subscription_repo import SubscriptionRepo
from notificationclientsdk.model.dto.resourcetype import ResourceType
from notificationclientsdk.model.dto.subscription import SubscriptionInfo
from notificationclientsdk.common.helpers.nodeinfo_helper import NodeInfoHelper
from notificationclientsdk.model.orm.subscription import Subscription as SubscriptionOrm
from notificationclientsdk.client.notificationservice import NotificationServiceClient
from notificationclientsdk.services.daemon import DaemonControl
from notificationclientsdk.common.helpers import subscription_helper

from notificationclientsdk.exception import client_exception

LOG = logging.getLogger(__name__)

from notificationclientsdk.common.helpers import log_helper
log_helper.config_logger(LOG)

class PtpService(object):

    def __init__(self, daemon_control):
        self.daemon_control = daemon_control
        self.locationservice_client = daemon_control.locationservice_client
        self.subscription_repo = SubscriptionRepo(autocommit=False)

    def __del__(self):
        del self.subscription_repo
        self.locationservice_client.cleanup()
        del self.locationservice_client
        return

    def query(self, broker_name):
        default_node_name = NodeInfoHelper.default_node_name(broker_name)
        nodeinfo_repo = NodeRepo(autocommit=False)
        nodeinfo = nodeinfo_repo.get_one(Status=1, NodeName=default_node_name)
        # check node availability from DB
        if not nodeinfo:
            raise client_exception.NodeNotAvailable(broker_name)
        else:
            broker_pod_ip = nodeinfo.PodIP
            supported_resource_types = json.loads(nodeinfo.ResourceTypes or '[]')
            if ResourceType.TypePTP in supported_resource_types:
                return self._query(default_node_name, broker_pod_ip)
            else:
                raise client_exception.ResourceNotAvailable(broker_name, ResourceType.TypePTP)

    def _query(self, broker_name, broker_pod_ip):
        # broker_host = "notificationservice-{0}".format(broker_name)
        broker_host = "[{0}]".format(broker_pod_ip)
        broker_transport_endpoint = "rabbit://{0}:{1}@{2}:{3}".format(
            self.daemon_control.daemon_context['NOTIFICATION_BROKER_USER'],
            self.daemon_control.daemon_context['NOTIFICATION_BROKER_PASS'],
            broker_host,
            self.daemon_control.daemon_context['NOTIFICATION_BROKER_PORT'])
        notificationservice_client = None
        try:
            notificationservice_client = NotificationServiceClient(
                broker_name, broker_transport_endpoint, broker_pod_ip)
            resource_status = notificationservice_client.query_resource_status(
                ResourceType.TypePTP, timeout=5, retry=10)
            return resource_status
        except oslo_messaging.exceptions.MessagingTimeout as ex:
            LOG.warning("ptp status is not available @node {0} due to {1}".format(
                broker_name, str(ex)))
            raise client_exception.ResourceNotAvailable(broker_name, ResourceType.TypePTP)
        except kombu.exceptions.OperationalError as ex:
            LOG.warning("Node {0} is unreachable yet".format(broker_name))
            raise client_exception.NodeNotAvailable(broker_name)
        finally:
            if notificationservice_client:
                notificationservice_client.cleanup()
                del notificationservice_client

    def add_subscription(self, subscription_dto):
        subscription_orm = SubscriptionOrm(**subscription_dto.to_orm())
        broker_name = subscription_dto.ResourceQualifier.NodeName
        default_node_name = NodeInfoHelper.default_node_name(broker_name)
        nodeinfos = NodeInfoHelper.enumerate_nodes(broker_name)
        # check node availability from DB
        if not nodeinfos or not default_node_name in nodeinfos:
            LOG.warning("Node {0} is not available yet".format(default_node_name))
            raise client_exception.NodeNotAvailable(broker_name)

        # get initial resource status
        if default_node_name:
            nodeinfo_repo = NodeRepo(autocommit=False)
            nodeinfo = nodeinfo_repo.get_one(Status=1, NodeName=default_node_name)
            broker_pod_ip = nodeinfo.PodIP
            ptpstatus = None
            ptpstatus = self._query(default_node_name, broker_pod_ip)
            LOG.info("initial ptpstatus:{0}".format(ptpstatus))

            # construct subscription entry
            subscription_orm.InitialDeliveryTimestamp = ptpstatus.get('EventTimestamp', None)
            entry = self.subscription_repo.add(subscription_orm)

            # Delivery the initial notification of ptp status
            subscription_dto2 = SubscriptionInfo(entry)
            try:
                subscription_helper.notify(subscription_dto2, ptpstatus)
                LOG.info("initial ptpstatus is delivered successfully")
            except Exception as ex:
                LOG.warning("initial ptpstatus is not delivered:{0}".format(str(ex)))
                raise client_exception.InvalidEndpoint(subscription_dto.EndpointUri)

            try:
                # commit the subscription entry
                self.subscription_repo.commit()
                self.daemon_control.refresh()
            except Exception as ex:
                LOG.warning("subscription is not added successfully:{0}".format(str(ex)))
                raise ex
        return subscription_dto2

    def remove_subscription(self, subscriptionid):
        try:
            # 1, delete entry
            self.subscription_repo.delete_one(SubscriptionId = subscriptionid)
            self.subscription_repo.commit()
            # 2, refresh daemon
            self.daemon_control.refresh()
        except Exception as ex:
            LOG.warning("subscription {0} is not deleted due to:{1}/{2}".format(
                self.subscriptionid, type(ex), str(ex)))
            raise ex
