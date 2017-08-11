# -*- coding: utf-8 -*-

from __future__ import unicode_literals, absolute_import
from functools import wraps

import os
import pika
import async_bowl
import pickle as compat_pickle
import configparser as compat_configparser

from pika.exceptions import ConnectionClosed

DEFAULT_CONFIG_FILE = 'config'

MAX_PRIORITY = 10


def heart_beat(func):
    @wraps(func)
    def wrap(self, *args, **kwargs):
        for _ in range(3):
            if not self._connect.is_open:
                assert self._connection
                self._connect = self._connection()
                self.initiate()
            try:
                rs = func(self, *args, **kwargs)
                return rs
            except ConnectionClosed:
                assert self._connection
                self._connect = self._connection()
                self.initiate()
                continue

    return wrap


class RabbitMQProxy(object):
    def __init__(self, host=None, port=None, username=None,
                 password=None, vhost=None, config_file=None):

        if vhost:
            self.host = host
            self.port = port
            self.username = username
            self.password = password
            self.vhost = vhost
        else:
            if not config_file:
                top_dir = os.path.dirname(async_bowl.__file__)
                config_file = os.path.join(top_dir, DEFAULT_CONFIG_FILE)
            else:
                config_file = config_file

            configparser = compat_configparser.ConfigParser()
            configparser.read_file(open(config_file))

            self.host = configparser.get('rabbitmq', 'host')
            self.port = configparser.getint('rabbitmq', 'port')
            self.username = configparser.get('rabbitmq', 'username')
            self.password = configparser.get('rabbitmq', 'password')
            self.vhost = configparser.get('rabbitmq', 'vhost')

        self._connect = self._connection()

    def _connection(self):
        if self.username:
            credentials = pika.PlainCredentials(self.username, self.password)
        else:
            credentials = None

        parameters = pika.ConnectionParameters(self.host, self.port, self.vhost, credentials)
        self._connect = pika.BlockingConnection(parameters=parameters)
        return self._connect

    def make_queue(self, namespace, name, raw=False,
                   max_priority=MAX_PRIORITY):
        return RabbitMQQueue(self._connect, namespace, name, raw=raw,
                             max_priority=max_priority, connection=self._connection)


class RabbitMQQueue(object):
    def __init__(self, connect, namespace, name, raw=False,
                 max_priority=MAX_PRIORITY, connection=None):
        self._connect = connect
        self._connection = connection
        self.namespace = namespace
        self.routing_key = namespace + name
        self.__raw = raw
        self.__max_priority = max_priority

        self.initiate()

    @property
    def max_priority(self):
        return self.__max_priority

    def initiate(self):
        self.channel = self._make_channel()
        self._queue_declare()

    def _queue_declare(self):
        arguments = {
            'x-max-priority': self.__max_priority,
            'ha-mode': 'all'
        }
        return self.channel.queue_declare(queue=self.routing_key, arguments=arguments, durable=True)

    def __len__(self):
        res = self._queue_declare()
        return res.method.message_count

    def _make_channel(self):
        return self._connect.channel()

    def _load_value(self, value):
        if value is not None:
            value = compat_pickle.loads(value)
        return value

    @heart_beat
    def put(self, value, priority=0):
        if priority is True:
            priority = self.__max_priority

        if self.__raw is False:
            value = compat_pickle.dumps(value)

        properties = pika.BasicProperties(priority=priority, delivery_mode=2)
        return self.channel.basic_publish(
            exchange='',
            routing_key=self.routing_key,
            properties=properties,
            body=value
        )

    @heart_beat
    def get(self):
        method, properties, body = self.channel.basic_get(queue=self.routing_key, no_ack=True)
        if self.__raw is True:
            return body
        else:
            value = self._load_value(body)
            return value

    @heart_beat
    def clear(self):
        return self.channel.queue_purge(queue=self.routing_key)

    @heart_beat
    def delete(self):
        return self.channel.queue_delete(queue=self.routing_key)

    def close(self):
        return self.channel.close()
