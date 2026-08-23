import dramatiq
from dramatiq.brokers.redis import RedisBroker
from dramatiq.middleware import CurrentMessage

from synapsekb.config import get_settings

broker: RedisBroker = RedisBroker(url=get_settings().redis_url)  # type: ignore[no-untyped-call]
broker.add_middleware(CurrentMessage())  # type: ignore[no-untyped-call]
dramatiq.set_broker(broker)
