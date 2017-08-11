# -*- coding: utf-8 -*-
from __future__ import absolute_import, print_function


class Item(object):
    # __slots__ = ['method', 'url', 'params', 'data', 'headers',
    # 'proxy', 'cookies', 'info', 'timeout', 'max_retry']

    def __init__(self, item_js):
        self.method = item_js.get('method', None)
        self.url = item_js.get('url', None)
        self.params = item_js.get('params', None)
        self.data = item_js.get('data', None)
        self.headers = item_js.get('headers', {})
        self.proxy = item_js.get('proxy', None)
        self.cookies = item_js.get('cookies', None)
        self.encoding = item_js.get('encoding', None)
        self.info = item_js.get('info', None)
        self.timeout = item_js.get('timeout', None)
        self.max_retry = item_js.get('max_retry', 1)

    def make_request_kwargs(self):
        assert self.method, 'Item.method is {}'.format(repr(self.method))

        kwargs = dict()

        kwargs['headers'] = self.headers

        if self.params:
            kwargs['params'] = self.params

        if self.data:
            kwargs['data'] = self.data

        kwargs['encoding'] = self.encoding

        kwargs['timeout'] = self.timeout

        kwargs['proxy'] = self.proxy

        kwargs['cookies'] = self.cookies

        return kwargs

    def json(self):
        js = dict(
            method=self.method,
            url=self.url,
            params=self.params,
            data=self.data,
            headers=self.headers,
            proxy=self.proxy,
            cookies=self.cookies,
            info=self.info,
            timeout=self.timeout,
            max_retry=self.max_retry,
        )
        return js
