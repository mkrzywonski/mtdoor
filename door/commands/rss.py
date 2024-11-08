import datetime

import requests
import feedparser
from loguru import logger as log
from pydantic import BaseModel, HttpUrl

from . import BaseCommand


class Feed(BaseModel):
    name: str
    short_name: str
    url: HttpUrl
    last_updated: datetime.datetime | None = None
    headlines: list[str] | None = None


FEEDS = [
    Feed(name="Meshtastic Blog", short_name="blog", url="https://meshtastic.org/blog/rss.xml"),
    Feed(name="Meshtastic Discourse", short_name="discourse", url="https://meshtastic.discourse.group/posts.rss"),
    Feed(name="RAK Wireless", short_name="rak", url="https://meshtastic.discourse.group/posts.rss"),
    Feed(name="Seed Studio", short_name="seeed", url="https://www.seeedstudio.com/blog/feed/"),
    Feed(name="Heltec", short_name="heltec", url="https://heltec.org/feed/"),
    Feed(name="The Comms Channel", short_name="tc2", url="https://www.thecommschannel.com/index.xml"),
    Feed(name="Jeff Geerling", short_name="geerling", url="https://www.jeffgeerling.com/blog/feed"),
]


def get_feed_titles(feed: Feed) -> list[str]:
    response = requests.get(feed.url)
    if response.status_code != 200:
        log.warning(f"Bad response from feed '{feed.short_name}")
        return
    parsed = feedparser.parse(response.text)
    if "entries" not in parsed:
        log.warning(f"No entries in feed response for '{feed.short_name}")
        return

    return [p["title"] for p in parsed["entries"]]


class RSS(BaseCommand):
    command = "rss"
    description = "returns headlines from RSS feeds"
    help = "Show feeds with 'rss list'."

    def load(self):
        # TODO read from configuration, feeds shouldn't be hard-coded
        self.feed_names = [f.short_name for f in FEEDS]

    def invoke(self, msg: str, node: str) -> str:
        self.run_in_thread(self.fetch, msg, node)

    def fetch(self, msg: str, node: str):
        # strip invocation command
        msg = msg[len(self.command) :].lower().lstrip().rstrip()

        # return a list
        if msg[:4] == "list":
            return self.send_dm(self.list_feeds(), node)

        # search for the requested feed
        feed: Feed
        found_feed: Feed = None
        for feed in FEEDS:
            if feed.short_name in msg:
                found_feed = feed
                break

        if found_feed:
            titles = get_feed_titles(feed)
            reply = self.build_reply(titles)
        else:
            reply = f"Feed not found. {self.list_feeds()}"

        self.send_dm(reply, node)

    def list_feeds(self) -> str:
        feed: Feed
        return "Installed RSS feeds:\n\n" + "\n".join(
            [f"{feed.short_name}: {feed.name}" for feed in FEEDS]
        )

    def build_reply(self, titles: list[str]) -> str:
        reply = ""
        for t in titles:
            proposed = f"{t}\n\n"
            if len(reply + proposed) > 200:
                break
            else:
                reply += proposed
        return reply.strip()
