"""Owner paneli, majburiy obuna, cookies, matnlar, xabar yuborish."""
from __future__ import annotations

import asyncio
import unittest

from tests.harness import Env
from tests import fakegram as fg

IG = "https://www.instagram.com/reel/De19WiVNiOj/"
COOKIES = "# Netscape HTTP Cookie File\n.instagram.com\tTRUE\t/\tTRUE\t2000000000\tsessionid\tabc\n"


class OwnerFlows(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.env = await Env.create(limit_mb=1)
        self.bot, self.dp, self.app = self.env.bot, self.env.dp, self.env.app
        self.owner = self.env.owner

    async def asyncTearDown(self):
        self.assertEqual(self.dp.errors, [])
        self.assertEqual(self.app.inflight, set())
        await self.env.close()

    async def panel(self):
        return (await self.owner.say("/admin"))[0]

    async def test_non_admin_ignored(self):
        u = self.env.client(5)
        new = await u.say("/admin")
        self.assertFalse([m for m in new if m.reply_markup])
        cq = fg.CallbackQuery(self.bot, u.user, (await self.panel()), "ad:stats")
        await self.dp.feed(cq)
        self.assertEqual(self.dp.errors, [])

    async def test_panel_and_stats(self):
        await self.env.client(5).say(IG)
        p = await self.panel()
        await self.owner.press(p, "Statistika")
        self.assertIn("Jami", p.text)
        await self.owner.press(p, "Ortga")
        await self.owner.press(p, "Yopish")

    async def test_cookies_upload_valid_invalid_delete(self):
        p = await self.panel()
        await self.owner.press(p, "Cookies")
        await self.owner.press_data(p, "ad:cp:instagram")
        self.bot.download_bytes = b"garbage"
        new = await self.owner.send_doc("cookies.txt")
        self.assertTrue(any("o'xshamaydi" in (m.text or "") for m in new))
        self.bot.download_bytes = COOKIES.encode()
        new = await self.owner.send_doc("cookies.txt")
        self.assertTrue(any("saqlandi" in (m.text or "") for m in new))
        self.assertTrue(self.app.media.cookie_path("instagram").exists())
        await self.env.client(6).say(IG)
        self.assertIsNotNone(self.env.ytdlp_calls(audio=False)[-1]["cookiefile"])
        p = await self.panel()
        await self.owner.press(p, "Cookies")
        await self.owner.press_data(p, "ad:cd:instagram")
        self.assertFalse(self.app.media.cookie_path("instagram").exists())
        # matn sifatida yopishtirish
        await self.owner.press_data(p, "ad:cp:instagram")
        new = await self.owner.say(COOKIES)
        self.assertTrue(self.app.media.cookie_path("instagram").exists())

    async def test_text_edit_reset_and_button_label(self):
        p = await self.panel()
        await self.owner.press(p, "Matnlar")
        await self.owner.press_data(p, "ad:tl:uz")
        await self.owner.press_data(p, "ad:te:uz:start")
        await self.owner.press_data(p, "ad:tw:uz:start")
        new = await self.owner.say("Salom <b>{name}</b> 💎")
        self.assertTrue(any("Saqlandi" in (m.text or "") for m in new))
        start = (await self.env.client(7, "Vali").say("/start"))[0]
        self.assertIn("Salom <b>Vali</b>", start.text)
        await self.owner.press_data(p, "ad:te:uz:start")
        await self.owner.press_data(p, "ad:tr:uz:start")
        start = (await self.env.client(8, "Vali").say("/start"))[0]
        self.assertIn("Assalomu", start.text)
        # tugma matni
        await self.owner.press_data(p, "ad:tw:uz:btn_add_group")
        await self.owner.say("Guruhga ulash")
        start = (await self.env.client(9).say("/start"))[0]
        self.assertEqual(start.reply_markup.flat()[0].text, "Guruhga ulash")
        # noto'g'ri o'zgaruvchi bot qulamasligi kerak
        await self.owner.press_data(p, "ad:tw:uz:start")
        await self.owner.say("Salom {nomalum} {")
        start = (await self.env.client(10).say("/start"))[0]
        self.assertTrue(start.text)

    async def test_image_set_and_delete(self):
        p = await self.panel()
        await self.owner.press(p, "Rasmlar")
        await self.owner.press_data(p, "ad:iw:start")
        await self.owner.send_photo()
        self.assertTrue(await self.app.db.get_setting("img_start", ""))
        self.assertTrue((await self.env.client(11).say("/start"))[0].photo)
        await self.owner.press_data(p, "ad:id:start")
        self.assertFalse(await self.app.db.get_setting("img_start", ""))

    async def test_settings_toggles_and_values(self):
        p = await self.panel()
        await self.owner.press(p, "Sozlamalar")
        await self.owner.press_data(p, "ad:tg:caption_on")
        res = [m for m in await self.env.client(12).say(IG) if m.video][0]
        self.assertFalse(res.caption and "orqali" in res.caption, "caption o'chirilgan bo'lishi kerak")
        await self.owner.press_data(p, "ad:sv:max_playlist_items")
        self.assertTrue(any("1 dan 10" in (m.text or "") for m in await self.owner.say("99")))
        await self.owner.say("4")
        self.assertEqual(await self.app.db.get_setting("max_playlist_items"), "4")
        await self.owner.press_data(p, "ad:sv:cobalt_url")
        self.assertTrue(any("http" in (m.text or "") for m in await self.owner.say("zzz")))
        await self.owner.say("https://c.example.com/")
        self.assertEqual(await self.app.db.get_setting("cobalt_url"), "https://c.example.com/")
        await self.owner.press_data(p, "ad:sv:cobalt_url")
        await self.owner.say("-")
        self.assertEqual(await self.app.db.get_setting("cobalt_url"), "")

    async def test_admin_management(self):
        p = await self.panel()
        await self.owner.press(p, "Adminlar")
        await self.owner.press_data(p, "ad:aa")
        await self.owner.say("777")
        self.assertTrue(self.app.is_admin(777))
        new = await self.env.client(777).say("/admin")
        self.assertTrue(new, "yangi admin panelga kira olishi kerak")
        self.assertNotIn("Adminlar", [b.text for b in new[0].reply_markup.flat()], "oddiy admin boshqa admin qo'sha olmaydi")
        await self.owner.press_data(p, "ad:ar:777")
        self.assertFalse(self.app.is_admin(777))

    # ------------------------------------------------------------ majburiy obuna
    def add_channel(self, cid=-1001, username="chan"):
        self.bot.known_chats[f"@{username}"] = fg.Chat(cid, "channel", title="Kanal", username=username)
        self.bot.members[(cid, 0)] = "x"

    async def test_forced_subscription_cycle(self):
        self.add_channel()
        p = await self.panel()
        await self.owner.press(p, "Majburiy obuna")
        await self.owner.press_data(p, "ad:sa")
        new = await self.owner.say("@chan")
        self.assertTrue(any("Qo'shildi" in (m.text or "") for m in new), [m.text for m in new])
        self.assertEqual(len(await self.app.db.channels()), 1)

        u = self.env.client(20)
        new = await u.say("salom qidiruv")
        gate = new[0]
        self.assertIn("https://t.me/chan", [b.url for b in gate.reply_markup.flat()])
        self.assertEqual(self.env.ytdlp_calls(), [], "obunasiz yuklash bo'lmasligi kerak")
        self.assertTrue((await u.say("/start")), "/start obunasiz ham ishlaydi")
        _, cq = await u.press(gate, "Tasdiqlash")
        self.assertTrue(cq.answers[-1][1], "a'zo bo'lmasa alert")
        self.bot.members[(-1001, 20)] = "member"
        await u.press(gate, "Tasdiqlash")
        self.assertTrue(gate.deleted)
        new = await u.say(IG)
        self.assertTrue([m for m in new if m.video])
        # admin har doim o'tadi
        self.assertTrue([m for m in await self.owner.say(IG) if m.video])
        # o'chirish tugmasi
        p = await self.panel()
        await self.owner.press(p, "Majburiy obuna")
        await self.owner.press(p, "O‘chirish")
        self.assertTrue([m for m in await self.env.client(21).say(IG) if m.video])

    async def test_broken_channel_fails_open(self):
        await self.app.db.add_channel(-1002, "Eski", "https://t.me/old")
        self.bot.broken_chats.add(-1002)
        new = await self.env.client(22).say(IG)
        self.assertTrue([m for m in new if m.video], "bot kanalidan chiqarilgan bo'lsa foydalanuvchi to'xtamasligi kerak")

    async def test_channel_add_errors(self):
        p = await self.panel()
        await self.owner.press(p, "Majburiy obuna")
        await self.owner.press_data(p, "ad:sa")
        new = await self.owner.say("@yoq_kanal")
        self.assertTrue(any("topilmadi" in (m.text or "") for m in new))
        self.bot.known_chats["@private"] = fg.Chat(-1003, "channel", title="Yopiq")
        new = await self.owner.say("@private")
        self.assertTrue(any("Taklif" in (m.text or "") or "Qo'shildi" in (m.text or "") for m in new))
        await self.owner.say("noto'g'ri")
        await self.owner.say("https://t.me/+abc")
        await self.owner.say("/cancel")

    # ------------------------------------------------------------ xabar yuborish
    async def test_broadcast_with_blocked_and_retry(self):
        for i in range(1, 6):
            await self.env.client(100 + i).say("/start")
        self.bot.blocked.add(102)
        self.bot.retry_after_once.add(103)
        p = await self.panel()
        await self.owner.press(p, "Xabar yuborish")
        new = await self.owner.say("Yangilik!")
        confirm = [m for m in new if m.reply_markup][0]
        await self.owner.press_data(confirm, "ad:bs")
        for _ in range(100):
            await asyncio.sleep(0.05)
            if any("tugadi" in (m.text or "") for m in self.bot.outbox):
                break
        self.assertTrue(any("tugadi" in (m.text or "") for m in self.bot.outbox))
        self.assertEqual((await self.app.db.get_user(102))["active"], 0)
        got = [m for m in self.bot.outbox if m.chat.id == 103 and (m.text or "").startswith("copy:")]
        self.assertEqual(len(got), 1, "RetryAfter dan keyin qayta yuborilishi kerak")

    async def test_fsm_does_not_swallow_user_flow(self):
        p = await self.panel()
        await self.owner.press(p, "Sozlamalar")
        await self.owner.press_data(p, "ad:sv:cobalt_url")
        await self.owner.say("/cancel")
        self.assertTrue([m for m in await self.owner.say(IG) if m.video])


class StartupTest(unittest.IsolatedAsyncioTestCase):
    async def test_main_starts_polling(self):
        from tests.harness import run_main_once
        info = await run_main_once()
        self.assertTrue(info["polling"])
        self.assertTrue(info["webhook_deleted"])
        self.assertTrue(info["commands"])


if __name__ == "__main__":
    unittest.main()
