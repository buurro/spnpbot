from typing import Literal

from pydantic import BaseModel


class ExternalUrl(BaseModel):
    spotify: str


class Image(BaseModel):
    url: str
    width: int | None
    height: int | None


class Contextable(BaseModel):
    id: str
    name: str
    external_urls: ExternalUrl
    images: list[Image]

    @property
    def url(self) -> str:
        return self.external_urls.spotify

    @property
    def thumbnail(self) -> Image:
        return self.images[-1]


class SimplifiedArtist(BaseModel):
    id: str
    name: str
    external_urls: ExternalUrl

    @property
    def url(self) -> str:
        return self.external_urls.spotify


class Show(Contextable): ...


class Episode(BaseModel):
    id: str
    name: str
    show: Show
    external_urls: ExternalUrl

    @property
    def url(self) -> str:
        return self.external_urls.spotify

    @property
    def thumbnail(self) -> Image:
        return self.show.images[-1]


class Album(Contextable):
    artists: list[SimplifiedArtist]

    @property
    def artist(self) -> SimplifiedArtist:
        return self.artists[0]


class Artist(Contextable): ...


class Playlist(Contextable): ...


class Track(BaseModel):
    id: str
    name: str
    artists: list[SimplifiedArtist]
    external_urls: ExternalUrl
    album: Album

    @property
    def thumbnail(self) -> Image:
        return self.album.images[-1]

    @property
    def url(self) -> str:
        return self.external_urls.spotify

    @property
    def artist(self) -> SimplifiedArtist:
        return self.artists[0]


Item = Track | Episode


class Context(BaseModel):
    type: str
    uri: str


class CurrentlyPlayingResponse(BaseModel):
    is_playing: bool
    currently_playing_type: Literal["track", "episode", "ad", "unknown"]
    item: Item | None
    context: Context | None

    @property
    def track(self) -> Track | None:
        if isinstance(self.item, Track):
            return self.item
        return None


class PlayedItem(BaseModel):
    track: Track
    context: Context | None


class RecentlyPlayedResponse(BaseModel):
    items: list[PlayedItem]


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["Bearer"]
    scope: str
    expires_in: int


class RefreshTokenResponse(BaseModel):
    access_token: str
    token_type: Literal["Bearer"]
    scope: str
    expires_in: int
