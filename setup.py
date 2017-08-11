from setuptools import setup, find_packages

setup(
    name='async_bowl',
    version='0.0.1',
    description='An Async Distributed Crawling Framework.',
    packages=find_packages(),
    url='https://github.com/Jiramew/async_bowl',
    license='BSD License',
    author='Jiramew',
    author_email='hanbingflying@sina.com',
    maintainer='Jiramew',
    maintainer_email='hanbingflying@sina.com',
    platforms=["all"],
    classifiers=[
        'Development Status :: 3 - Alpha',
        'License :: OSI Approved :: BSD License',
        'Programming Language :: Python',
        "Programming Language :: Python :: 3",
        'Programming Language :: Python :: 3.6',
        'Topic :: Software Development :: Libraries'
    ],
    install_requires=[
        'pika>=1.0.1',
        'mugen>=0.4.3',
        'redis>=2.10.5',
        'redis-py-cluster>=1.3.6',
    ]
)
