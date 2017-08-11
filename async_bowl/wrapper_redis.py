# -*- coding: utf-8 -*-
from __future__ import unicode_literals, absolute_import

import os
import redis
import logging
import async_bowl
import rediscluster

import pickle as compat_pickle
import configparser as compat_configparser

DEFAULT_CONFIG_FILE = 'config'
CMD_KEYS = 'ASYNC_BOWL_REDIS_KEYS'


class NoRedisProxy(Exception): pass


class UnknownRedisPingType(Exception): pass


def _request(redis_conn, cmd, *args, **kwargs):
    if kwargs.get('redis_proxy'):
        redis_proxy = kwargs['redis_proxy']
    else:
        redis_proxy = None

    while True:
        try:
            result = getattr(redis_conn, cmd)(*args)
            return result
        except Exception as err:
            logging.error('[ERROR]: redis_conn: {} {}, {}'.format(cmd, args, err))

            if not is_connection_live(redis_conn):
                # reconnect redis
                if redis_proxy is None:
                    raise NoRedisProxy('redis_conn is die, redis_proxy is missing, can\'t reconnect to redis')
                redis_conn = redis_proxy._connection()


def is_connection_live(redis_conn):
    try:
        rs = redis_conn.ping()
    except:
        return False

    if not rs:
        return False

    if isinstance(rs, bool) and rs:  # simple server
        return True
    elif isinstance(rs, bool) and not rs:  # simple server
        return False
    elif isinstance(rs, dict):  # cluster
        return any(list(rs.values()))
    else:
        raise UnknownRedisPingType(repr(rs))


class RedisProxyBasic(object):
    def _connection(self):
        if self.is_cluster:
            self._connect = rediscluster.StrictRedisCluster(
                startup_nodes=self.startup_nodes, decode_responses=self.decode_responses)
        else:
            self._connect = redis.StrictRedis(host=self.host,
                                              port=self.port,
                                              db=self.db,
                                              password=self.password,
                                              **self.kwargs)
        return self._connect

    def make_set(self, name, raw=False):
        return RedisSet(self.namespace + name, self._connect,
                        redis_proxy=self, raw=raw)

    def make_list(self, name, maxsize=None, raw=False):
        return RedisList(self.namespace + name, self._connect,
                         maxsize=maxsize, redis_proxy=self, raw=raw)

    def make_hash(self, name, raw=False):
        return RedisHash(self.namespace + name, self._connect,
                         redis_proxy=self, raw=raw)

    def make_string(self, name, raw=False):
        return RedisString(self.namespace + name, self._connect,
                           redis_proxy=self, raw=raw)


class RedisProxy(RedisProxyBasic):
    def __init__(self, namespace, host=None, port=None,
                 password=None, db=0, config_file=None, **kwargs):
        self.namespace = namespace
        self.kwargs = kwargs
        self.is_cluster = False

        if host is None:
            if not config_file:
                top_dir = os.path.dirname(async_bowl.__file__)
                config_file = os.path.join(top_dir, DEFAULT_CONFIG_FILE)
            else:
                config_file = config_file

            configparser = compat_configparser.ConfigParser()
            configparser.read_file(open(config_file))

            self.password = configparser.get('redis', 'password')
            self.host = configparser.get('redis', 'host')
            self.port = configparser.get('redis', 'port')
            self.db = configparser.get('redis', 'db')
        else:
            self.password = password
            self.host = host
            self.port = port
            self.db = db

        if not self.password:
            self.password = None
        if not self.host:
            self.host = 'localhost'
        if not self.port:
            self.port = 6379
        else:
            self.port = int(self.port)

        if not self.db:
            self.db = 0
        else:
            self.db = int(self.db)

        self._connection()


class RedisClusterProxy(RedisProxyBasic):
    def __init__(self, namespace, startup_nodes=None, password=None,
                 config_file=None, decode_responses=False, **kwargs):

        self.namespace = namespace
        self.kwargs = kwargs
        self.is_cluster = True
        self.decode_responses = decode_responses

        if startup_nodes is None:
            if not config_file:
                top_dir = os.path.dirname(async_bowl.__file__)
                config_file = os.path.join(top_dir, DEFAULT_CONFIG_FILE)
            else:
                config_file = config_file

            configparser = compat_configparser.ConfigParser()
            configparser.readfp(open(config_file))

            self.password = configparser.get('rediscluster', 'password')
            nodes = configparser.get('rediscluster', 'startup_nodes')
            self.startup_nodes = self.make_startup_nodes(nodes)
        else:
            self.password = password
            self.startup_nodes = startup_nodes

        if not self.password:
            self.password = None
        if not self.startup_nodes:
            self.startup_nodes = [{'host': 'localhost', 'port': '6379'}]

        self._connection()

    def make_startup_nodes(self, nodes):
        startup_nodes = []
        ip_ports = [n.split(':') for n in nodes.split(',')]
        for ip, port in ip_ports:
            startup_nodes.append({'host': ip, 'port': port})
        return startup_nodes

    def _scan(self, cursor, match):
        keys = []
        cursors = []
        result = _request(self._connect, 'scan', cursor, match, redis_proxy=self)
        for _, val in result.items():
            keys += [i for i in val[1]]
            cr = val[0]
            if cr:
                cursors.append(cr)
        return keys, cursors

    def scan_iter(self, match, count=None, limit=None):
        result = _request(self._connect, 'scan_iter', match, count,
                          redis_proxy=self)
        if not limit:
            for item in result:
                yield item
        else:
            for index, item in enumerate(result):
                if index < limit:
                    yield item
                else:
                    return

    def keys(self, match, node):
        rs = _request(self._connect, '_execute_command_on_nodes', node,
                      CMD_KEYS, match, redis_proxy=self)
        return rs

    def keys_iter(self, match):
        nodes = _request(self._connect, 'determine_node', 'KEYS', redis_proxy=self)
        for node in nodes:
            if node['server_type'] == 'slave':
                for key in self.keys(match, [node]):
                    yield key


class RedisSet(object):
    def __init__(self, name, connect, redis_proxy=None, raw=False):
        self.name = name
        self._connect = connect
        self._redis_proxy = redis_proxy
        self.__raw = raw

    def _get_value(self):
        raw_value = self._get_raw_value()
        if self.__raw is True:
            return raw_value
        else:
            value = {self._load_value(member) for member in raw_value}
            return value

    def _get_raw_value(self):
        return _request(self._connect, 'smembers',
                        self.name, redis_proxy=self._redis_proxy)

    def _sscan_iter(self, match=None):
        for raw_value in _request(self._connect, 'sscan_iter', self.name, match,
                                  redis_proxy=self._redis_proxy):
            if self.__raw is True:
                yield raw_value
            else:
                value = self._load_value(raw_value)
                yield value

    def _load_value(self, value):
        if value is not None:
            value = compat_pickle.loads(value)
        return value

    def __contains__(self, value):
        if self.__raw is False:
            value = compat_pickle.dumps(value)
        return _request(self._connect, 'sismember', self.name, value,
                        redis_proxy=self._redis_proxy)

    def __iter__(self):
        return iter(self._sscan_iter())

    def __len__(self):
        return _request(self._connect, 'scard', self.name,
                        redis_proxy=self._redis_proxy)

    def add(self, *values):
        if self.__raw is True:
            values_t = values
        else:
            values_t = [compat_pickle.dumps(value) for value in values]
        result = _request(self._connect, 'sadd', self.name, *values_t,
                          redis_proxy=self._redis_proxy)
        return result

    def remove(self, *values):
        if self.__raw is True:
            values_t = values
        else:
            values_t = [compat_pickle.dumps(value) for value in values]
        result = _request(self._connect, 'srem', self.name, *values_t,
                          redis_proxy=self._redis_proxy)
        return result

    def delete(self):
        return _request(self._connect, 'delete', self.name,
                        redis_proxy=self._redis_proxy)


class RedisList(object):
    def __init__(self, name, connect, maxsize=None, redis_proxy=None, raw=False):
        self.name = name
        self._connect = connect
        self.maxsize = maxsize
        self.put = self.append
        self.get = self.popleft
        self._redis_proxy = redis_proxy
        self.__raw = raw

    def _get_value(self):
        raw_value = self._get_raw_value()
        if self.__raw is True:
            return raw_value
        else:
            value = [self._load_value(member) for member in raw_value]
            return value

    def _get_raw_value(self):
        return _request(self._connect, 'lrange', self.name, 0, -1,
                        redis_proxy=self._redis_proxy)

    def _load_value(self, value):
        if value is not None:
            value = compat_pickle.loads(value)
        return value

    def __iter__(self):
        size = len(self)
        for i in range(size):
            yield self[i]

    def __len__(self):
        return _request(self._connect, 'llen', self.name,
                        redis_proxy=self._redis_proxy)

    def __contains__(self, value):
        result = self.remove(value, num=1)
        if result == 1:
            self.append(value)
            return True
        else:
            return False

    def __getitem__(self, index):
        if isinstance(index, int):
            raw_value = _request(self._connect, 'lindex', self.name, index,
                                 redis_proxy=self._redis_proxy)
            if self.__raw is True:
                return raw_value
            else:
                value = self._load_value(raw_value)
                return value
        elif isinstance(index, slice):
            if index.step:
                raise ValueError('RedisList has not support "slice\'s step".')
            if any([not isinstance(i, int) for i in (index.start, index.stop)]):
                raise ValueError('slice\'s values must be int.')

            if index.start is not None and index.stop is None:
                raw_value = _request(self._connect, 'lrange', self.name, index.start, -1,
                                     redis_proxy=self._redis_proxy)
            elif index.start is not None and index.stop is not None:
                raw_value = _request(self._connect, 'lrange', self.name, index.start, index.stop,
                                     redis_proxy=self._redis_proxy)
            elif index.start is None and index.stop is not None:
                raw_value = _request(self._connect, 'lrange', self.name, 0, index.stop,
                                     redis_proxy=self._redis_proxy)
            else:
                return None

            if self.__raw is True:
                return raw_value
            else:
                value = [self._load_value(v) for v in raw_value]
                return value
        else:
            raise ValueError('%s does not be supported.' % type(index))

    def append(self, *values):
        if self.maxsize:
            if _request(self._connect, 'llen', self.name,
                        redis_proxy=self._redis_proxy) >= self.maxsize:
                return 0

        if self.__raw is True:
            values_t = values
        else:
            values_t = [compat_pickle.dumps(value) for value in values]

        result = _request(self._connect, 'rpush', self.name, *values_t,
                          redis_proxy=self._redis_proxy)
        return result

    def pop(self, block=False):
        if block:
            raw_value = _request(self._connect, 'brpop', self.name,
                                 redis_proxy=self._redis_proxy)[1]
        else:
            raw_value = _request(self._connect, 'rpop', self.name,
                                 redis_proxy=self._redis_proxy)
        if self.__raw is True:
            return raw_value
        else:
            value = self._load_value(raw_value)
            return value

    def appendleft(self, *values):
        if self.maxsize:
            if _request(self._connect, 'llen', self.name,
                        redis_proxy=self._redis_proxy) >= self.maxsize:
                return 0

        if self.__raw is True:
            values_t = values
        else:
            values_t = [compat_pickle.dumps(value) for value in values]
        result = _request(self._connect, 'lpush', self.name, *values_t,
                          redis_proxy=self._redis_proxy)
        return result

    def popleft(self, block=False):
        if block:
            raw_value = _request(self._connect, 'blpop', self.name,
                                 redis_proxy=self._redis_proxy)[1]
        else:
            raw_value = _request(self._connect, 'lpop', self.name,
                                 redis_proxy=self._redis_proxy)
        if self.__raw is True:
            return raw_value
        else:
            value = self._load_value(raw_value)
            return value

    def rpoplpush(self, obj):
        if not isinstance(obj, RedisList):
            raise TypeError('%s is not an instance of RedisList.' % obj)
        return _request(self._connect, 'rpoplpush', self.name, obj.name,
                        redis_proxy=self._redis_proxy)

    def remove(self, value, num=1):
        if self.__raw is False:
            value = compat_pickle.dumps(value)
        return _request(self._connect, 'lrem', self.name, num, value,
                        redis_proxy=self._redis_proxy)

    def empty(self):
        return not len(self)

    def delete(self):
        return _request(self._connect, 'delete', self.name,
                        redis_proxy=self._redis_proxy)


class RedisHash(object):
    def __init__(self, name, connect, redis_proxy=None, raw=False):
        self.name = name
        self._connect = connect
        self._redis_proxy = redis_proxy
        self.__raw = raw

    def _get_value(self):
        raw_value = self._get_raw_value()
        if self.__raw is True:
            return raw_value
        else:
            return {self._load_value(key): self._load_value(val) \
                    for key, val in raw_value.items()}

    def _get_raw_value(self):
        return _request(self._connect, 'hgetall', self.name,
                        redis_proxy=self._redis_proxy)

    def _hscan_iter(self, match=None):
        for rk, rv in _request(self._connect, 'hscan_iter', self.name, match,
                               redis_proxy=self._redis_proxy):
            if self.__raw is True:
                yield (rk, rv)
            else:
                k = self._load_value(rk)
                v = self._load_value(rv)
                yield (k, v)

    def _load_value(self, value):
        if value is not None:
            value = compat_pickle.loads(value)
        return value

    def __contains__(self, key):
        if self.__raw is False:
            key = compat_pickle.dumps(key)
        return _request(self._connect, 'hexists', self.name, key,
                        redis_proxy=self._redis_proxy)

    def __len__(self):
        return _request(self._connect, 'hlen', self.name,
                        redis_proxy=self._redis_proxy)

    def __iter__(self):
        return iter(self.keys())

    def keys(self):
        raw_keys = _request(self._connect, 'hkeys', self.name,
                            redis_proxy=self._redis_proxy)
        if self.__raw is True:
            return raw_keys
        else:
            return [self._load_value(key) for key in raw_keys]

    def values(self):
        raw_values = _request(self._connect, 'hvals', self.name,
                              redis_proxy=self._redis_proxy)
        if self.__raw is True:
            return raw_values
        else:
            return [self._load_value(val) for val in raw_values]

    def items(self):
        raw_hash = self._get_raw_value()
        if self.__raw is True:
            return raw_hash.items()
        else:
            return [(self._load_value(key), self._load_value(val)) \
                    for key, val in raw_hash.items()]

    def itemiter(self):
        return iter(self._hscan_iter())

    def get(self, key):
        if self.__raw is False:
            key = compat_pickle.dumps(key)
        raw_value = _request(self._connect, 'hget', self.name, key,
                             redis_proxy=self._redis_proxy)
        if self.__raw is True:
            return raw_value
        else:
            value = self._load_value(raw_value)
            return value

    def set(self, key, value=None):
        if self.__raw is False:
            key = compat_pickle.dumps(key)
            value = compat_pickle.dumps(value)
        result = _request(self._connect, 'hset', self.name, key, value,
                          redis_proxy=self._redis_proxy)
        return result

    def setnx(self, key, value=None):
        if self.__raw is False:
            key = compat_pickle.dumps(key)
            value = compat_pickle.dumps(value)
        result = _request(self._connect, 'hsetnx', self.name, key, value,
                          redis_proxy=self._redis_proxy)
        return result

    def hincrby(self, key, value):
        assert isinstance(value, int), TypeError('{!r} is not int'.format(value))

        if self.__raw is False:
            key = compat_pickle.dumps(key)
        result = _request(self._connect, 'hincrby', self.name, key, value,
                          redis_proxy=self._redis_proxy)
        return result

    def exists(self, key):
        return self.__contains__(key)

    def remove(self, key):
        if self.__raw is False:
            key = compat_pickle.dumps(key)
        return _request(self._connect, 'hdel', self.name, key,
                        redis_proxy=self._redis_proxy)

    def delete(self):
        return _request(self._connect, 'delete', self.name,
                        redis_proxy=self._redis_proxy)


class RedisString(object):
    def __init__(self, name, connect, redis_proxy=None, raw=False):
        self.name = name
        self._connect = connect
        self._redis_proxy = redis_proxy
        self._value = None
        self.__raw = raw

    def __iadd__(self, num):
        if not isinstance(num, int):
            raise TypeError('RedisString.__iadd__ expects one int argument')

        self.incr(num)
        return self

    def _get_value(self):
        raw_value = self._get_raw_value()
        if self.__raw is True:
            return raw_value
        else:
            return self._load_value(raw_value)

    def _get_raw_value(self):
        return _request(self._connect, 'get', self.name,
                        redis_proxy=self._redis_proxy)

    def _load_value(self, value):
        if value is not None:
            value = compat_pickle.loads(value)
        return value

    def get(self, sync=False):
        if sync is True:
            return self._get_value()
        else:
            return self._value

    def set(self, value):
        self._value = value
        if self.__raw is False:
            value = compat_pickle.dumps(value)
        result = _request(self._connect, 'set', self.name, value,
                          redis_proxy=self._redis_proxy)
        return result

    def setex(self, value, ttl):
        self._value = value
        if self.__raw is False:
            value = compat_pickle.dumps(value)
        result = _request(self._connect, 'setex', self.name, ttl, value,
                          redis_proxy=self._redis_proxy)
        return result

    def incr(self, num):
        result = _request(self._connect, 'incr', self.name, num,
                          redis_proxy=self._redis_proxy)
        return result

    def exists(self):
        result = _request(self._connect, 'exists', self.name,
                          redis_proxy=self._redis_proxy)
        return result

    def delete(self):
        result = _request(self._connect, 'delete', self.name,
                          redis_proxy=self._redis_proxy)
        return result
