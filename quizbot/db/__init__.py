from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


def database(url: str):
    kwargs = {"pool_pre_ping": True}
    if url.startswith("postgresql"):
        kwargs.update(connect_args={"server_settings": {"statement_timeout": "30000"}})
    engine = create_async_engine(url, **kwargs)
    return engine, async_sessionmaker(engine, expire_on_commit=False)
