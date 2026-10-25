from fastapi import FastAPI, Depends
from sqlalchemy.orm import Session
from fastapi.responses import RedirectResponse
from database import Base , engine, get_db
from datetime import datetime,timezone,timedelta
from sqlalchemy.exc import IntegrityError
from models import DataMapping
import string
from redis_client import redis_client
import json 
from schemas import URLCreate, URLResponse, URLUpdate
import secrets

import redis
import time 
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from database import get_db
from models import DataMapping

app=FastAPI()

ALPHABET=string.ascii_letters + string.digits


# generate the short code 
def generate_short_code(length : int = 7) -> str:
    return "".join(
        secrets.choice(ALPHABET)
        for _ in range(length)
    )

# lua script - that deletes the lock only if its token matches the current request token
RELEASE_LOCK = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("DEL", KEYS[1])
else
    return 0
end
"""

Base.metadata.create_all(bind=engine) # this will create all the tables that are not existing but it does not modify the existing model
# for the changes in the existing table we have to use the alembic migrations 

def generate_expiration_time(days : int):
    return datetime.now(timezone.utc) + timedelta(days=days)


def get_cached_mapping(short_code: str):
    try:
        cache_data = redis_client.get(short_code)
    except redis.exceptions.RedisError:
        return None

    if cache_data is None:
        return None

    try:
        cached_dict = json.loads(cache_data)
        cached_url = cached_dict.get("long_url")

        if not cached_url:
            return None

        expired_at_str = cached_dict.get("expired_at")
        expired_at = (
            datetime.fromisoformat(expired_at_str)
            if expired_at_str
            else None
        )

        if expired_at is not None:
            if expired_at.tzinfo is None:
                expired_at = expired_at.replace(
                    tzinfo=timezone.utc
                )

            if expired_at <= datetime.now(timezone.utc):
                raise HTTPException(
                    status_code=410,
                    detail="Short URL has expired",
                )

        return cached_dict

    except (json.JSONDecodeError, TypeError, ValueError):
        return None
@app.get('/') # get method to empty endpoint
def first_response():
    return {"response": "first"}


@app.post("/urls", response_model=URLResponse)
def create_short_url(payload :URLCreate , db :Session =Depends(get_db) ):
    
        max_retires=3
        for _ in range(max_retires):
            short_code = generate_short_code()
            expired_at = generate_expiration_time(payload.days)
            record=DataMapping(
                short_code=short_code,
                long_url=str(payload.long_url),
                expired_at=expired_at,

                
            )
            try: 
                db.add(record)
                db.commit()
                db.refresh(record)
                return record
            except IntegrityError:
                db.rollback()
                print("Database integrity rule violated")
   
        raise HTTPException(
            status_code=503,
            detail="Could not generate a unique short code. Please try again."
        )

        

    
    


@app.get("/{short_code}")
def redirect_url(
    short_code: str,
    db: Session = Depends(get_db),
):
    # check if short code is present in the cache
    cached_dict = get_cached_mapping(short_code)

    if cached_dict is not None:
        return RedirectResponse(
            url=cached_dict["long_url"],
            status_code=302,
        )

    # if it is not present into the cache 
    lock_key = f"lock:{short_code}"
    lock_token = secrets.token_hex(16)
    lock_acquired = False

    try:
        lock_acquired = bool(
            redis_client.set(
                lock_key,
                lock_token,
                nx=True,
                ex=5,
            )
        )
    except redis.exceptions.RedisError:
      # if redis is unavailable pass to the postgres
        pass

    try:
        if not lock_acquired:
            # Another request may be populating the cache.
            # Wait briefly and retry Redis.
            for _ in range(10):
                time.sleep(0.1)

                cached_dict = get_cached_mapping(short_code)

                if cached_dict is not None:
                    return RedirectResponse(
                        url=cached_dict["long_url"],
                        status_code=302,
                    )

        else:
           # Double-check cache after acquiring lock
            cached_dict = get_cached_mapping(short_code)

            if cached_dict is not None:
                return RedirectResponse(
                    url=cached_dict["long_url"],
                    status_code=302,
                )

       # check. to the postgres 
        record = (
            db.query(DataMapping)
            .filter(DataMapping.short_code == short_code)
            .first()
        )

        if record is None:
            raise HTTPException(
                status_code=404,
                detail="Short URL not found",
            )

        now = datetime.now(timezone.utc)
        expired_at = record.expired_at

        if expired_at is not None:
            if expired_at.tzinfo is None:
                expired_at = expired_at.replace(
                    tzinfo=timezone.utc
                )

            if expired_at <= now:
                raise HTTPException(
                    status_code=410,
                    detail="Short URL has expired",
                )

      # store in redis populate 
        cache_data = json.dumps({
            "long_url": record.long_url,
            "expired_at": (
                expired_at.isoformat()
                if expired_at is not None
                else None
            ),
        })

        try:
            if expired_at is not None:
                ttl = int((expired_at - now).total_seconds())

                if ttl > 0:
                    redis_client.set(
                        short_code,
                        cache_data,
                        ex=ttl,
                    )
            else:
                redis_client.set(
                    short_code,
                    cache_data,
                    ex=3600,
                )

        except redis.exceptions.RedisError:
            # PostgreSQL still has the mapping
            pass

        # 6. Redirect
        return RedirectResponse(
            url=record.long_url,
            status_code=302,
        )

    finally:
        # Release only the lock we own
        if lock_acquired:
            try:
                redis_client.eval(
                    RELEASE_LOCK,
                    1,
                    lock_key,
                    lock_token,
                )
            except redis.exceptions.RedisError:
                # The lock will eventually expire automatically.
                pass
# status code 302 means a redirecred url is temporaritly moved to the another path or url. 

@app.patch("/urls/{short_code}")
def update_short_url(short_code , payload : URLUpdate, db : Session= Depends(get_db)):
     # find the url in the postgres 
     record=(db.query(DataMapping).filter(DataMapping.short_code == short_code).first())

     if record is None:
        raise HTTPException(
            status_code=404,
            detail="Short URL not found",
        )
     # don't allow updates to the expired url. 
     now= datetime.now(timezone.utc)
     expired_at=record.expired_at
     if expired_at is not None:
          if expired_at.tzinfo is None:
               expired_at = expired_at.replace(tzinfo=timezone.utc)
     if expired_at <= now:
            raise HTTPException(
                status_code=410,
                detail="Short URL has expired",
            )
    

     record.long_url = str(payload.long_url)
     try:
        db.commit()
        db.refresh(record)
     except Exception:
        db.rollback()
        raise
     # invalidate the old cache entryn
     try:
          redis_client.delete(short_code)
     except redis.exceptions.RedisError:
          pass
     return {
        "short_code": record.short_code,
        "long_url": record.long_url,
        "expired_at": record.expired_at,
    }

