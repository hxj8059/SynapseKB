from typing import Any

import dramatiq
from dramatiq.brokers.redis import RedisBroker
from dramatiq.middleware import CurrentMessage, Middleware

from synapsekb.config import get_settings


class DurableMessageId(Middleware):
    def before_enqueue(self, broker: Any, message: Any, delay: Any) -> None:
        # RedisBroker allocates its id before this hook and serializes afterwards.
        # Persisting our chosen id before sending closes the send/SQL-commit gap.
        key = message.options.get("dispatch_message_key")
        if key:
            message.options["redis_message_id"] = key


broker: RedisBroker = RedisBroker(  # type: ignore[no-untyped-call]
    url=get_settings().redis_url,
    socket_connect_timeout=5,
    socket_timeout=5,
)
broker.add_middleware(CurrentMessage())  # type: ignore[no-untyped-call]
broker.add_middleware(DurableMessageId())  # type: ignore[no-untyped-call]
dramatiq.set_broker(broker)
