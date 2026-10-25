import redis 
redis_client=redis.Redis(
    host='localhost',
    port=6379,
    decode_responses=True,
    socket_connect_timeout=1,
    socket_timeout=1,
)

