# -*- coding: utf-8 -*-
from __future__ import absolute_import

import os
import json
import signal
import argparse

from functools import wraps
from async_bowl.exceptions import NotCommand
from async_bowl.models import CacheInferface, QueueInferface
from async_bowl.utils import md5_string, serialize_obj, unserialize_obj

HOME = os.path.expanduser('~')
LOCAL_CACHE_DIR = os.path.join(HOME, '.cache', 'async_bowl')
PIDS = {'master': [], 'slave': []}
KILL_SIGNAL = signal.SIGINT
KILL_TERM = signal.SIGTERM


def parse_arguments(argv):
    p = argparse.ArgumentParser(description='async_bowl')

    p.add_argument('xxx', type=str, nargs='*', help='command and args')
    p.add_argument('-s', '--slave', action='store_true', help='slave')
    p.add_argument('-o', '--others', nargs='*', action='store', help='other arguments')

    args = p.parse_args(argv)

    return args


def hash_key(func):
    @wraps(func)
    def wrapper(*args):
        self = args[0]
        h = md5_string(args[1])
        rs = func(self, h)
        return rs

    return wrapper


class Adapter:
    def __init__(self, queue, cache):
        assert isinstance(queue, QueueInferface)
        assert isinstance(cache, CacheInferface)

        if not cache.initiated:
            cache.initiate()
        self._queue = queue
        self._cache = cache
        self._current_tasks = {}
        self.tdx = 0

    @property
    def queue(self):
        return self._queue

    @property
    def cache(self):
        return self._cache

    @staticmethod
    def parse_args(argv):
        args = parse_arguments(argv)
        if not args.xxx:
            raise NotCommand()

        args.comd = args.xxx[0]
        args.opts = args.xxx[1:]

        return args

    def register(self, namespace):
        self._cache.register(namespace)

    @staticmethod
    def get_pids(script_filename):
        pid_file = os.path.join(LOCAL_CACHE_DIR, script_filename + '.pids.json')
        if not os.path.exists(pid_file):
            return dict(PIDS)

        pids = json.load(open(pid_file))
        return pids

    @staticmethod
    def save_pids(pids, script_filename):
        pid_file = os.path.join(LOCAL_CACHE_DIR, script_filename + '.pids.json')
        if not os.path.exists(LOCAL_CACHE_DIR):
            os.makedirs(LOCAL_CACHE_DIR)

        with open(pid_file, 'w') as fd:
            json.dump(pids, fd)

    @staticmethod
    def kill(pid):
        os.kill(pid, KILL_SIGNAL.value)

    def restore_current_tasks(self):
        for k, v in self._current_tasks.items():
            self._queue.put(v, priority=True)  # max_priority

    def get_task(self):
        task = self._queue.get()
        if not task:
            return 0, task
        else:
            tdx = self.tdx
            self.tdx += 1

            # add task to current tasks
            self._current_tasks[tdx] = task
            u_task = unserialize_obj(task)
            return tdx, u_task

    def task_over(self, tdx):
        try:
            del self._current_tasks[tdx]
        except Exception as e:
            print("Error {0}".format(e))
            pass

    def add_task(self, task, priority=0):
        s_task = serialize_obj(task)
        self._queue.put(s_task, priority=priority)

    @hash_key
    def task_done(self, task_name):
        self._cache.table_set(0, task_name, 1)

    @hash_key
    def is_task_done(self, task_name):
        return self._cache.in_table(0, task_name)

    @hash_key
    def queue_add(self, task_name):
        self._cache.table_incr(1, task_name, 1)

    @hash_key
    def is_in_queue(self, task_name):
        return self._cache.in_table(1, task_name)

    @hash_key
    def queue_remove(self, task_name):
        val = self._cache.table_incr(1, task_name, -1)
        if not val or val < 1:
            self._cache.table_del(1, task_name)

    @hash_key
    def miss_task(self, task_name):
        self._cache.table_del(0, task_name)
        self._cache.table_del(1, task_name)

    def clear_cache(self):
        self._cache.table_clear(0)
        self._cache.table_clear(1)

    def clear_queue(self):
        self._queue.delete()
