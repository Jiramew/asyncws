# -*- coding: utf-8 -*-
from __future__ import absolute_import

import os
import sys
import json
import time
import signal
import asyncio
import logging

from functools import partial
from mugen.session import Session
from async_bowl.exceptions import UnknownCommand
from async_bowl.models import make_queue, make_cache
from async_bowl.adapter import Adapter, KILL_SIGNAL, KILL_TERM

DEFAULT_CACHE_BACKEND = 'redis'
DEFAULT_QUEUE_BACKEND = 'redis'


class AsyncLoop:
    def __init__(self,
                 concurrency=10,
                 cache_backend=DEFAULT_CACHE_BACKEND,
                 queue_backend=DEFAULT_QUEUE_BACKEND,
                 debug=True,
                 config_file=None):

        self.__debug = debug
        self.__stop = False
        self.__started = False

        self._script_filename = None
        self._arguments = None

        self.concurrency = concurrency
        self.__task_amount = 0

        queue = make_queue(queue_backend, self.NAME, config_file=config_file)
        cache = make_cache(cache_backend, self.NAME, config_file=config_file)
        self.adapter = Adapter(queue, cache)

        self.pid = os.getpid()

    def __build_loop(self):
        self.main_loop = asyncio.get_event_loop()
        self.main_loop.set_debug(self.__debug)
        self.__lock = asyncio.Lock()

    @property
    def lock(self):
        return self.__lock

    async def __task_sleep(self):
        if hasattr(self, 'task_internal'):
            await asyncio.sleep((self.task_internal or 0))

    async def __watch_task_queue(self):
        while True:

            if self.__stop is True:
                break

            await self.__task_sleep()

            if self.__task_amount < self.concurrency:
                tdx, task = self.adapter.get_task()
                if not task:
                    await asyncio.sleep(0.1)
                    continue

                task_name = None
                if len(task) == 3:
                    generator_name, args, task_name = task
                else:
                    generator_name, args = task

                if not hasattr(self, str(generator_name)):
                    self.adapter.task_over(tdx)
                    continue

                generator = getattr(self, generator_name)
                _task = asyncio.ensure_future(generator(*args),
                                              loop=self.main_loop)
                _task.add_done_callback(
                    partial(self.__uncache_current_queue_task, task_name, tdx))
                self.__task_amount += 1
            else:
                await asyncio.sleep(0.1)

    def __uncache_current_queue_task(self, task_name, tdx, future):
        if task_name:
            self.adapter.queue_remove(task_name)

        self.__task_amount -= 1

        if future.exception():
            return

        self.adapter.task_over(tdx)

    def __cache_current_queue_task(self, task_name):
        self.adapter.queue_add(task_name)

    def add_task(self, generator_name, *args, task_name=None, repeat=True, priority=0):
        if task_name is not None:
            if not repeat:
                if self.adapter.is_in_queue(task_name):
                    return None

                if self.adapter.is_task_done(task_name):
                    return None

            self.__cache_current_queue_task(task_name)

        self.adapter.add_task((generator_name, args, task_name),
                              priority=priority)

    def task_done(self, task_name):
        self.adapter.task_done(task_name)

    def uncache_task(self, *task_names):
        for task_name in task_names:
            self.adapter.miss_task(task_name)

    def __start_master(self):
        self.__build_loop()

        asyncio.ensure_future(self.__watch_task_queue(), loop=self.main_loop)
        asyncio.ensure_future(self.run(), loop=self.main_loop)
        self.main_loop.run_forever()

    def __start_slave(self):
        self.__build_loop()

        asyncio.ensure_future(self.__watch_task_queue(), loop=self.main_loop)
        self.main_loop.run_forever()

    def start(self):
        self.__handle_signal()
        self._script_filename = sys.argv[0]
        argv = sys.argv[1:]
        args = self.adapter.parse_args(argv)
        self._arguments = args
        comd = args.comd
        opts = args.opts
        pid = self.pid
        self.__slave = args.slave
        self.__started = True

        self.adapter.register(self.NAME)

        if comd == 'start':
            pids = self.adapter.get_pids(self._script_filename)
            if self.__slave:
                pids['slave'].append(pid)
            else:
                pids['master'].append(pid)
            self.adapter.save_pids(pids, self._script_filename)

            try:
                if self.__slave:
                    self.__start_slave()
                else:
                    if not hasattr(self, 'run'):
                        raise NotImplementedError('run is not implemented')
                    else:
                        self.__start_master()
            except Exception:
                pass
            finally:
                key = ('master', 'slave')[self.__slave]
                pids = self.adapter.get_pids(self._script_filename)
                if self.pid in pids[key]:
                    pids[key].remove(pid)
                self.adapter.save_pids(pids, self._script_filename)

        elif comd == 'stop':
            print('command:', comd)
            print('script_filename:', self._script_filename)

            if opts:
                pids = self.adapter.get_pids(self._script_filename)
                master_pids = set()
                slave_pids = set()
                for opt in opts:
                    opt = opt.lower()
                    if opt == 'all':
                        master_pids.update(pids['master'])
                        slave_pids.update(pids['slave'])
                    elif opt[0] in ('s', 'm') and opt[1:].isdigit():
                        key = ('master', 'slave')[opt[0] == 's']
                        n = int(opt[1:])
                        if key == 'master':
                            master_pids.update(pids[key][:n])
                        else:
                            slave_pids.update(pids[key][:n])

                for pid in master_pids:
                    self.adapter.kill(pid)
                    time.sleep(1)
                    print('Kill: {} - {}'.format('master', pid))

                for pid in slave_pids:
                    self.adapter.kill(pid)
                    time.sleep(1)
                    print('Kill: {} - {}'.format('slave', pid))

        elif comd == 'clear':
            print('command:', comd)
            print('script_filename:', self._script_filename)

            if not opts:
                yes = input('CLEAR ALL ? (Yes/No) ')
                if not yes or yes.lower() == 'No':
                    return
                elif yes and yes.lower() == 'Yes':
                    print('Clear cache')
                    self.adapter.clear_cache()
                    print('Clear queue')
                    self.adapter.clear_queue()
            else:
                for opt in opts:
                    if opt == 'cache':
                        print('Clear cache')
                        self.adapter.clear_cache()
                    elif opt == 'queue':
                        print('Clear queue')
                        self.adapter.clear_queue()
                    else:
                        raise UnknownCommand(opt)
        else:
            raise UnknownCommand(comd)

    def stop(self):
        self.__stop = True
        logging.info('[async_loop] STOP')

    def __handle_signal(self):
        signal.signal(KILL_SIGNAL, self.__signal_handler)

    def __signal_handler(self, signum, frame):
        if not self.__started:
            return

        logging.info('[signal_handler]: signal_num: {}, pid: {}'.format(signum, self.pid))

        self.stop()
        self.adapter.restore_current_tasks()
        pids = self.adapter.get_pids(self._script_filename)
        key = ('master', 'slave')[self.__slave]
        if self.pid in pids[key]:
            pids[key].remove(self.pid)
        self.adapter.save_pids(pids, self._script_filename)
        self.__exit()

    def __exit(self):
        os.kill(self.pid, KILL_TERM)

    async def async_web_request(self, item, session=None, keep_alive=True, check_html=None):
        if item.method is None:
            return None

        session = (session or Session())

        check_html = (check_html or self.check_html)

        _err = None
        for _ in range((item.max_retry or 1)):
            request_kwargs = item.make_request_kwargs()
            if session.headers:
                del request_kwargs['headers']
            try:
                response = await session.request(item.method,
                                                 item.url,
                                                 recycle=keep_alive,
                                                 **request_kwargs)
                html_string = response.text
                if not check_html(html_string):
                    continue
                return response
            except Exception as err:
                _err = err
                continue

        logging.error('[error]: web_request: {}, {}'.format(
            json.dumps(item.json(), ensure_ascii=False), _err))
        return None

    def check_html(self, html_string):
        return True
