import re

from async_bowl.task_pool import AsyncLoop
from async_bowl.item import Item


class SomeSpider(AsyncLoop):
    NAME = 'Some_spider'

    def __init__(self):
        super(SomeSpider, self).__init__(concurrency=10,
                                         cache_backend='redis',
                                         queue_backend='redis',
                                         config_file='./config.example',
                                         debug=True)

    async def run(self):
        item = Item(dict(
            method='GET',
            url='https://www.v2ex.com/',
        ))
        self.add_task('get_articles', item, task_name=item.url)

    async def get_articles(self, item):
        resp = await self.async_web_request(item)
        html = resp.text
        titles = re.findall(r'<a href="/t/\d+">(.+?)</a>', html)
        for title in titles:
            print('title:', title)
        self.task_done(item.url)


if __name__ == '__main__':
    loop = SomeSpider()
    loop.start()
