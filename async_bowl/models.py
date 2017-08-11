# -*- coding: utf-8 -*-
from __future__ import absolute_import

import os

from async_bowl.wrapper_redis import RedisProxy
from async_bowl.wrapper_rabbitmq import RabbitMQProxy
from async_bowl.exceptions import UnknownBackend

DEFAULT_CONFIG_FILE = 'config'
ASYNC_BOWL_NAMESPACES = 'ASYNC_BOWL'


class QueueInferface:
    def initiate(self):
        raise NotImplementedError()

    def put(self, item, priority=0):
        raise NotImplementedError()

    def get(self):
        raise NotImplementedError()

    def close(self):
        raise NotImplementedError()

    def purge(self):
        raise NotImplementedError()

    def delete(self):
        raise NotImplementedError()


class CacheInferface:
    def initiate(self):
        raise NotImplementedError()

    def register(self, namespace):
        raise NotImplementedError()

    def table_set(self, index, key, value):
        raise NotImplementedError()

    def table_get(self, index, key):
        raise NotImplementedError()

    def table_del(self, index, key):
        raise NotImplementedError()

    def table_incr(self, index, key, num):
        raise NotImplementedError()

    def in_table(self, index, key):
        raise NotImplementedError()

    def table_items(self, index):
        raise NotImplementedError()

    def table_clear(self, index):
        raise NotImplementedError()


class RabbitMQQueue(QueueInferface):
    def __init__(self, namespace, config_file=None):
        self._initiated = False
        self.namespace = namespace
        self.config_file = config_file or os.path.join(os.path.dirname(__file__), DEFAULT_CONFIG_FILE)
        self.initiate()

    def __len__(self):
        return len(self._queue)

    def initiate(self):
        self._rabbitmq_proxy = RabbitMQProxy(config_file=self.config_file)
        self._queue = self._rabbitmq_proxy.make_queue(self.namespace + '.', 'task_queue', raw=False)
        self._initiated = True

    def put(self, item, priority=0):
        return self._queue.put(item, priority=priority)

    def get(self):
        return self._queue.get()

    def close(self):
        return self._queue.close()

    def purge(self):
        return self._queue.clear()

    def delete(self):
        return self._queue.delete()


class RedisQueue(QueueInferface):
    def __init__(self, namespace, config_file=None, redis_proxy=None):
        self.namespace = namespace
        config_file = config_file or os.path.join(os.path.dirname(__file__), DEFAULT_CONFIG_FILE)
        redis_proxy = redis_proxy or RedisProxy(namespace + '.', config_file=config_file)
        self._redis_proxy = redis_proxy
        self._connect = redis_proxy._connect
        self.initiate()

    def initiate(self):
        self.queue = self._redis_proxy.make_list('task_queue', raw=True)

    def put(self, item, priority=0):
        if priority:
            return self.queue.appendleft(item)
        else:
            return self.queue.append(item)

    def get(self):
        return self.queue.popleft(block=False)

    def close(self):
        return

    def purge(self):
        return self.queue.delete()

    def delete(self):
        return self.queue.delete()


class RedisCache(CacheInferface):
    def __init__(self, namespace, config_file=None, redis_proxy=None):
        self._initiated = False
        self.namespace = namespace
        config_file = config_file or os.path.join(os.path.dirname(__file__), DEFAULT_CONFIG_FILE)
        redis_proxy = redis_proxy or RedisProxy(namespace + '.', config_file=config_file)
        self._redis_proxy = redis_proxy
        self._connect = redis_proxy._connect

        self.initiate()

    @property
    def initiated(self):
        return self._initiated

    @property
    def redis_proxy(self):
        return self._redis_proxy

    def initiate(self):
        self.table = self._redis_proxy.make_string('', raw=True)
        self.table_size = self._redis_proxy.make_string('', raw=True)
        register_set = self._redis_proxy.make_set('', raw=True)
        register_set.name = ASYNC_BOWL_NAMESPACES
        self.register_set = register_set
        self._initiated = True

    def register(self, namespace):
        self.register_set.add(namespace)

    def _make_table_key(self, index, key):
        k = '{}.tb{}.{}'.format(self.namespace, index, key)
        return k

    def table_set(self, index, key, value):
        self.table.name = self._make_table_key(index, key)
        is_existed = self.table.exists()
        self.table.set(value)
        if not is_existed:
            self.table_size.name = self._make_table_key(index, '')[:-1] + ':size'
            self.table_size += 1

    def table_get(self, index, key):
        self.table.name = self._make_table_key(index, key)
        val = self.table.get(sync=True)
        try:
            val = int(val)
            return val
        except Exception:
            return val

    def table_del(self, index, key):
        self.table.name = self._make_table_key(index, key)
        ok = self.table.delete()
        if ok:
            self.table_count(index, -1)

    def table_count(self, index, n):
        self.table_size.name = self._make_table_key(index, '')[:-1] + ':size'
        self.table_size += n
        val = self.table_size.get(sync=True)
        try:
            val = int(val)
            if val <= 0:
                self.table_size.delete()
        except Exception:
            pass

    def table_incr(self, index, key, num):
        self.table.name = self._make_table_key(index, key)
        is_existed = self.table.exists()
        rs = self.table.incr(num)
        if not is_existed:
            self.table_size.name = self._make_table_key(index, '')[:-1] + ':size'
            self.table_size += 1
        return rs

    def in_table(self, index, key):
        self.table.name = self._make_table_key(index, key)
        return self.table.exists()

    def table_items(self, index):
        match = self._make_table_key(index, '') + '*'
        keys_iter = self._redis_proxy.keys_iter(match)
        kvs = []
        for key in set(keys_iter):
            key = key.decode('utf-8')
            k = key.split('.')[-1]
            v = self.table_get(index, key)
            kvs.append((k, v))
        return kvs

    def table_keys_iter(self, index):
        match = self._make_table_key(index, '') + '*'
        keys_iter = self._redis_proxy.keys_iter(match)
        for key in keys_iter:
            key = key.decode('utf-8')
            yield key

    def table_clear(self, index):
        for key in self.table_keys_iter(index):
            self.table.name = key
            ok = self.table.delete()
            if ok:
                self.table_count(index, -1)


class SsdbCache(RedisCache):
    def __init__(self, *args, **kwargs):
        super(SsdbCache, self).__init__(*args, **kwargs)

    def initiate(self):
        self.table = self._redis_proxy.make_string('', raw=True)
        self.table_size = self._redis_proxy.make_string('', raw=True)
        register_set = self._redis_proxy.make_hash('', raw=True)
        register_set.name = ASYNC_BOWL_NAMESPACES
        self.register_set = register_set
        self._initiated = True

    def register(self, namespace):
        self.register_set.set(namespace, '')


def make_cache(tp, namespace, config_file=None):
    if tp == 'redis':
        return RedisCache(namespace, config_file=config_file)
    elif tp == 'ssdb':
        return SsdbCache(namespace, config_file=config_file)
    else:
        raise UnknownBackend(tp)


def make_queue(tp, namespace, config_file=None):
    if tp == 'redis':
        return RedisQueue(namespace, config_file=config_file)
    elif tp == 'rabbitmq':
        return RabbitMQQueue(namespace, config_file=config_file)
    else:
        raise UnknownBackend(tp)
