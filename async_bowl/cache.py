# -*- coding: utf-8 -*-
from __future__ import absolute_import, print_function

import os
import logging
import async_bowl

from async_bowl.wrapper_redis import RedisClusterProxy
from async_bowl.item import Item
from async_bowl.utils import has_http_policy

DEFAULT_CONFIG_FILE = 'config'


class Cache(object):
    def __init__(self, config_file=None):
        if config_file is not None:
            config_file = os.path.join(os.path.dirname(async_bowl.__file__), DEFAULT_CONFIG_FILE)
        redis_proxy = RedisClusterProxy('async_bowl.', config_file=config_file)
        self._connect = redis_proxy._connect

    def get_proxy(self, item=None):
        if isinstance(item, Item):
            if item.proxy and has_http_policy(item.proxy):
                return item.proxy

        proxy = self.get_proxy_from_db()
        if proxy is None:
            logging.warning('critical', 'DB has not proxy')
            return None

        proxy = 'http://{}'.format(proxy.decode('utf8'))
        return proxy

    def get_proxy_from_db(self):
        proxy = self._connect.lpop('async_bowl.proxy_queue')
        if proxy:
            self._connect.rpush('async_bowl.proxy_queue', proxy)
        return proxy
