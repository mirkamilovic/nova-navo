"""Stress: 300 foydalanuvchi bir vaqtda tasodifiy harakatlar qiladi."""
from __future__ import annotations

import asyncio
import random
import unittest

from tests.harness import Env
from tests.fake_ytdlp import FakeYoutubeDL

LINKS = [
    "https://www.instagram.com/reel/AAA111/", "https://www.instagram.com/reel/BBB222/",
    "https://www.tiktok.com/@a/video/333", "https://youtu.be/abcdefghijk",
    "https://www.tiktok.com/@a/video/big444", "https://www.instagram.com/p/album5/",
    "https://www.instagram.com/reel/login6/", "https://example.com/unsupported",
    "https://www.pinterest.com/pin/photo7/",
]
QUERIES = ["onam chiroyli", "yulduz", "nothing", "hello world", "boom query", "qo'shiq"]


class Stress(unittest.IsolatedAsyncioTestCase):
    async def test_300_users(self):
        env = await Env.create(limit_mb=1, parallel=4)
        FakeYoutubeDL.delay = 0.01
        rnd = random.Random(7)

        async def user(uid):
            u = env.client(uid, f"U{uid}")
            await u.say("/start")
            for _ in range(rnd.randint(2, 5)):
                act = rnd.choice(["link", "link", "search", "search", "top", "settings", "voice", "my"])
                try:
                    if act == "link":
                        await u.say(rnd.choice(LINKS))
                    elif act == "search":
                        new = await u.say(rnd.choice(QUERIES))
                        res = [m for m in new if m.reply_markup and m.text and m.text.startswith("🎧")]
                        if res:
                            btns = [b for b in res[0].reply_markup.flat() if (b.callback_data or "").startswith("sd:")
                                    or (b.callback_data or "").startswith("sm:")]
                            if btns:
                                await u.press_data(res[0], rnd.choice(btns).callback_data)
                    elif act == "top":
                        await u.say(rnd.choice(["/top", "/new"]))
                    elif act == "settings":
                        await u.say("/settings")
                    elif act == "voice":
                        await u.send_media("voice")
                    else:
                        await u.say("/my")
                except Exception as e:  # noqa: BLE001
                    self.fail(f"foydalanuvchi {uid}: {e!r}")

        await asyncio.wait_for(asyncio.gather(*(user(i) for i in range(1, 301))), 120)
        self.assertEqual(env.dp.errors, [], env.dp.errors[:3])
        self.assertLessEqual(FakeYoutubeDL.max_active, 4, "MAX_PARALLEL buzilmasligi kerak")
        self.assertEqual(env.app.inflight, set())
        self.assertEqual(env.tmp_dirs(), [], "vaqtinchalik papkalar qolmasligi kerak")
        links = [c for c in env.ytdlp_calls(audio=False)]
        self.assertGreater(len(links), 0)
        await env.close()

    async def test_same_link_burst_downloads_once(self):
        env = await Env.create(limit_mb=1, parallel=4)
        FakeYoutubeDL.delay = 0.05
        url = "https://www.instagram.com/reel/SAME999/"
        await asyncio.gather(*(env.client(i).say(url) for i in range(1, 41)))
        got = [m for m in env.bot.outbox if m.video]
        self.assertEqual(env.dp.errors, [])
        self.assertLessEqual(len(env.ytdlp_calls(audio=False)), 3, "bir xil havola qayta-qayta yuklanmasligi kerak")
        self.assertGreaterEqual(len(got), 1)
        self.assertEqual(env.tmp_dirs(), [])
        await env.close()


if __name__ == "__main__":
    unittest.main()
