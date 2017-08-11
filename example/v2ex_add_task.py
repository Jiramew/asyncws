from async_bowl.task_pool import AsyncLoop
from async_bowl.item import Item


class V2exSpider(AsyncLoop):
    NAME = 'Some_spider'

    def __init__(self):
        super(V2exSpider, self).__init__(
            concurrency=10,
            cache_backend='redis',
            queue_backend='redis')


if __name__ == '__main__':
    loop = V2exSpider()
    item = Item(dict(
        method='GET',
        url='https://www.v2ex.com/',
    ))
    loop.add_task('get_articles', item, task_name=item.url)
