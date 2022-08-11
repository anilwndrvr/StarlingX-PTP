#
# Copyright (c) 2021-2022 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

import json
import logging

import multiprocessing as mp
import threading
import time
from datetime import datetime, timezone

from notificationclientsdk.model.dto.subscription import SubscriptionInfoV1
from notificationclientsdk.model.dto.subscription import SubscriptionInfoV2
from notificationclientsdk.model.dto.resourcetype import ResourceType

from notificationclientsdk.repository.subscription_repo import SubscriptionRepo

from notificationclientsdk.common.helpers import subscription_helper
from notificationclientsdk.common.helpers.nodeinfo_helper import NodeInfoHelper

from notificationclientsdk.client.notificationservice import NotificationHandlerBase

LOG = logging.getLogger(__name__)

from notificationclientsdk.common.helpers import log_helper
log_helper.config_logger(LOG)



class NotificationHandler(NotificationHandlerBase):

    def __init__(self):
        self.__supported_resource_types = (ResourceType.TypePTP,)
        self.__init_notification_channel()
        pass

    def __init_notification_channel(self):
        self.notification_lock = threading.Lock()
        self.notification_stat = {}

    # def handle_notification_delivery(self, notification_info):
    def handle(self, notification_info):
        LOG.debug("start notification delivery")
        subscription_repo = None
        try:
            self.notification_lock.acquire()
            subscription_repo = SubscriptionRepo(autocommit=True)
            resource_type = notification_info.get('ResourceType', None)
            # Get nodename from resource address
            if resource_type:
                node_name = notification_info.get('ResourceQualifier', {}).get('NodeName', None)
                if not resource_type:
                    raise Exception("abnormal notification@{0}".format(node_name))
                if not resource_type in self.__supported_resource_types:
                    raise Exception("notification with unsupported resource type:{0}".format(resource_type))
                this_delivery_time = notification_info['EventTimestamp']
            else:
                source = notification_info.get('source', None)
                values = notification_info.get('data', {}).get('values', [])
                resource_address = values[0].get('ResourceAddress', None)
                if not resource_address:
                    raise Exception("No resource address in notification source".format(source))
                _,node_name,_ = subscription_helper.parse_resource_address(resource_address)
                this_delivery_time = notification_info['time']
                # Change time from float to ascii format
                notification_info['time'] = datetime.fromtimestamp(this_delivery_time).strftime('%Y-%m-%dT%H:%M:%S%fZ')
                # notification_info['time'] = time.strftime('%Y-%m-%dT%H:%M:%SZ',
                #                                           time.gmtime(this_delivery_time))

            entries = subscription_repo.get(Status=1)
            for entry in entries:
                subscriptionid = entry.SubscriptionId
                if entry.ResourceAddress:
                    _,entry_node_name,_ = subscription_helper.parse_resource_address(entry.ResourceAddress)
                    subscription_dto2 = SubscriptionInfoV2(entry)
                else:
                    ResourceQualifierJson = entry.ResourceQualifierJson or '{}'
                    ResourceQualifier = json.loads(ResourceQualifierJson)
                    # qualify by NodeName
                    entry_node_name = ResourceQualifier.get('NodeName', None)
                    subscription_dto2 = SubscriptionInfoV1(entry)
                node_name_matched = NodeInfoHelper.match_node_name(entry_node_name, node_name)
                if not node_name_matched:
                    continue

                try:
                    last_delivery_time = self.__get_latest_delivery_timestamp(node_name, subscriptionid)
                    if last_delivery_time and last_delivery_time >= this_delivery_time:
                        # skip this entry since already delivered
                        LOG.debug("Ignore the outdated notification for: {0}".format(entry.SubscriptionId))
                        continue

                    subscription_helper.notify(subscription_dto2, notification_info)
                    LOG.debug("notification is delivered successfully to {0}".format(
                        entry.SubscriptionId))

                    self.update_delivery_timestamp(node_name, subscriptionid, this_delivery_time)

                except Exception as ex:
                    LOG.warning("notification is not delivered to {0}:{1}".format(
                        entry.SubscriptionId, str(ex)))
                    # proceed to next entry
                    continue
                finally:
                    pass
            LOG.debug("Finished notification delivery")
            return True
        except Exception as ex:
            LOG.warning("Failed to delivery notification:{0}".format(str(ex)))
            return False
        finally:
            self.notification_lock.release()
            if not subscription_repo:
                del subscription_repo

    def __get_latest_delivery_timestamp(self, node_name, subscriptionid):
        last_delivery_stat = self.notification_stat.get(node_name,{}).get(subscriptionid,{})
        last_delivery_time = last_delivery_stat.get('EventTimestamp', None)
        return last_delivery_time

    def update_delivery_timestamp(self, node_name, subscriptionid, this_delivery_time):
        if not self.notification_stat.get(node_name, None):
            self.notification_stat[node_name] = {
                subscriptionid: {
                    'EventTimestamp': this_delivery_time
                    }
                }
            LOG.debug("delivery time @node: {0},subscription:{1} is added".format(
                node_name, subscriptionid))
        elif not self.notification_stat[node_name].get(subscriptionid, None):
            self.notification_stat[node_name][subscriptionid] = {
                'EventTimestamp': this_delivery_time
                }
            LOG.debug("delivery time @node: {0},subscription:{1} is added".format(
                node_name, subscriptionid))
        else:
            last_delivery_stat = self.notification_stat.get(node_name,{}).get(subscriptionid,{})
            last_delivery_time = last_delivery_stat.get('EventTimestamp', None)
            if (last_delivery_time and last_delivery_time >= this_delivery_time):
                return
            last_delivery_stat['EventTimestamp'] = this_delivery_time
            LOG.debug("delivery time @node: {0},subscription:{1} is updated".format(
                node_name, subscriptionid))
