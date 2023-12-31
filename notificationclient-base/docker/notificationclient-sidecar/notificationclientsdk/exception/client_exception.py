#
# Copyright (c) 2021-2022 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

class NodeNotAvailable(Exception):
    def __init__(self, node_name):
        self.node_name = node_name

    def __str__(self):
        return "Node:{0} not available".format(self.node_name)


class ResourceNotAvailable(Exception):
    def __init__(self, node_name, resource_type):
        self.node_name = node_name
        self.resource_type = resource_type

    def __str__(self):
        return "Resource with type:{0} is not available on node:{1}".format(
            self.resource_type, self.node_name)


class InvalidEndpoint(Exception):
    def __init__(self, endpoint_uri):
        self.endpoint_uri = endpoint_uri

    def __str__(self):
        return "Endpoint is invalid: {0}".format(self.endpoint_uri)

class InvalidResource(Exception):
    def __init__(self, resource):
        self.resource = resource

    def __str__(self):
        return "Resource is invalid: {0}".format(self.resource)

class InvalidSubscription(Exception):
    def __init__(self, subscriptioninfo):
        self.subscriptioninfo = subscriptioninfo

    def __str__(self):
        return "Subscription is invalid:{0}".format(
            self.subscriptioninfo.to_dict())

class SubscriptionAlreadyExists(Exception):
    def __init__(self, subscriptioninfo):
        self.subscriptioninfo = subscriptioninfo

    def __str__(self):
        return "Subscription already exists: {0}".format(
            self.subscriptioninfo)

class ServiceError(Exception):
    def __init__(self, code, *args):
        super().__init__(args)
        self.code = code

    def __str__(self):
        return str(self.code)
