from pydantic_settings import BaseSettings

class Settings (BaseSettings):
    sqlalchemy_string: str = "postgresql://gicdev:root@localhost/url_shortener_db"

settings=Settings()