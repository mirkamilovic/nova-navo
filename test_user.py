"""Foydalanuvchi oqimlari: /start, qidiruv, havola, Shazam, playlist, top/new, sozlamalar."""
from __future__ import annotations

import unittest

from tests.harness import Env, real_mp3
from tests import fakegram as fg
from tests.fake_ytdlp import FakeYoutubeDL

IG = "https://www.instagram.com/reel/De19WiVNiOj/?igsh=abc"


class UserFlows(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.env = await Env.create(limit_mb=1)
        self.bot, self.dp, self.app = self.env.bot, self.env.dp, self.env.app

    async def asyncTearDown(self):
        self.assertEqual(self.dp.errors, [], "handlerlarda xato bo'lmasligi kerak")
        self.assertEqual(self.app.inflight, set(), "inflight tozalanishi kerak")
        self.assertEqual(self.env.tmp_dirs(), [], "vaqtinchalik papkalar qolib ketmasligi kerak")
        await self.env.close()

    # ---------------------------------------------------------------- start
    async def test_start_and_commands(self):
        u = self.env.client(1, "Ali <b>")
        new = await u.say("/start")
        self.assertEqual(len(new), 1)
        self.assertIn("Ali &lt;b&gt;", new[0].text, "ism HTML dan tozalanishi kerak")
        self.assertIn("Instagram", new[0].text)
        btn = new[0].reply_markup.flat()[0]
        self.assertEqual(btn.url, "https://t.me/navotestbot?startgroup=true")
        self.assertEqual([c.command for c in self.bot.commands["BotCommandScopeAllPrivateChats"]],
                         ["my", "playlist", "top", "new", "settings"])
        self.assertIn("admin", [c.command for c in self.bot.commands[1000]])
        self.assertTrue(self.bot.description and self.bot.short_description)
        self.assertEqual(await u.say("/id") and u.last().text, "🆔 <code>1</code>")
        row = await self.app.db.get_user(1)
        self.assertEqual(row["first_name"], "Ali <b>")

    async def test_start_with_image(self):
        await self.app.db.set_setting("img_start", "PHOTOID")
        self.bot.files["PHOTOID"] = "photo"
        new = await self.env.client(2).say("/start")
        self.assertTrue(new[0].photo, "rasm bilan yuborilishi kerak")
        self.assertIn("Xush kelibsiz", new[0].caption)

    async def test_start_with_broken_image_falls_back_to_text(self):
        await self.app.db.set_setting("img_start", "NOT-A-REAL-FILE")
        new = await self.env.client(2).say("/start")
        self.assertIn("Xush kelibsiz", new[0].text)

    # ---------------------------------------------------------------- qidiruv
    async def test_search_pagination_and_audio(self):
        u = self.env.client(3)
        new = await u.say("onam chiroyli")
        res = new[0]
        self.assertTrue(res.text.startswith("🎧"))
        self.assertEqual(res.text.count("\n") - 1, 5, "sahifada 5 ta natija")
        self.assertIsNotNone(u.find(res, "Video"))
        self.assertIsNotNone(u.find(res, "➡️"))
        self.assertIsNone(u.find(res, "⬅️"))
        # keyingi sahifa
        await u.press(res, "➡️")
        self.assertIn("6. ", res.text)
        self.assertIsNotNone(u.find(res, "⬅️"))
        await u.press(res, "⬅️")
        self.assertIn("1. ", res.text)
        # audio tanlash
        new, cq = await u.press(res, data=None, label="2") if False else await u.press_data(res, res.reply_markup.flat()[2].callback_data)
        audio = [m for m in new if m.audio][0]
        self.assertIn("@navotestbot", audio.caption)
        self.assertTrue(audio.audio.performer)
        self.assertIsNotNone(u.find(audio, "❤️/💔"))
        self.assertIsNotNone(u.find(audio, "🎛"))
        self.assertEqual(len(self.env.ytdlp_calls(audio=True)), 1)
        # ikkinchi foydalanuvchi — keshdan, yt-dlp chaqirilmaydi
        u2 = self.env.client(4)
        res2 = (await u2.say("onam chiroyli"))[0]
        new2, _ = await u2.press_data(res2, res2.reply_markup.flat()[2].callback_data)
        self.assertTrue([m for m in new2 if m.audio])
        self.assertEqual(len(self.env.ytdlp_calls(audio=True)), 1, "kesh ishlashi kerak")

    async def test_search_toggle_to_video(self):
        u = self.env.client(5)
        res = (await u.say("qo'shiq"))[0]
        await u.press(res, "Video")
        self.assertIsNotNone(u.find(res, "Audio"))
        new, _ = await u.press_data(res, res.reply_markup.flat()[1].callback_data)
        vids = [m for m in new if m.video]
        self.assertEqual(len(vids), 1)
        self.assertIn("youtube.com/watch?v=vid0", self.env.ytdlp_calls(audio=False)[0]["url"])

    async def test_search_nothing_found_and_error(self):
        u = self.env.client(6)
        new = await u.say("nothing here")
        self.assertIn("topilmadi", new[0].text)
        new = await u.say("boom query")
        self.assertTrue(any("Yuklab bo‘lmadi" in (m.text or "") for m in self.bot.outbox if m.chat.id == 6))

    async def test_short_text_and_commands_not_searched(self):
        u = self.env.client(7)
        self.assertEqual(await u.say("a"), [])
        self.assertEqual(await u.say("/unknowncommand"), [])

    async def test_stale_search_callback(self):
        u = self.env.client(8)
        res = (await u.say("abc def"))[0]
        await self.app.db._run("DELETE FROM searches")
        new, cq = await u.press_data(res, res.reply_markup.flat()[1].callback_data)
        self.assertTrue(cq.answers[-1][1], "eskirgan qidiruv alert bilan javob berishi kerak")

    # ---------------------------------------------------------------- havola
    async def test_instagram_video_flow(self):
        u = self.env.client(10)
        new = await u.say(IG)
        vid = [m for m in new if m.video][0]
        self.assertIn("orqali yuklab olindi", vid.caption)
        labels = [b.text for b in vid.reply_markup.flat()]
        self.assertTrue(any("Saqlash" in t for t in labels))
        self.assertTrue(any("Qo'shiqni yuklab olish" in t for t in labels))
        self.assertTrue(any("Guruhga" in t for t in labels))
        self.assertFalse([m for m in self.bot.outbox if m.chat.id == 10 and (m.text or "").startswith("⏳")
                          and not m.deleted], "holat xabari o'chirilishi kerak")
        # keshdan
        calls_before = len(self.env.ytdlp_calls())
        new2 = await self.env.client(11).say(IG + "&utm=1")
        self.assertTrue([m for m in new2 if m.video])
        self.assertEqual(len(self.env.ytdlp_calls()), calls_before, "tracking parametrli bir xil havola keshdan")
        # audio ajratish
        new3, _ = await u.press(vid, "Qo'shiqni yuklab olish")
        aud = [m for m in new3 if m.audio][0]
        self.assertEqual(aud.audio.performer, "Gulsanam")
        self.assertEqual(aud.audio.title, "Onam chiroyli")

    async def test_save_to_video_playlist_and_play_delete(self):
        u = self.env.client(12)
        vid = [m for m in await u.say(IG) if m.video][0]
        _, cq = await u.press(vid, "Saqlash")
        self.assertIn("Saqlandi", cq.answers[-1][0])
        _, cq = await u.press(vid, "Saqlash")
        self.assertIn("allaqachon", cq.answers[-1][0])
        pl = (await u.say("/playlist"))[0]
        self.assertIn("1. ", pl.text)
        new, _ = await u.press_data(pl, pl.reply_markup.flat()[0].callback_data)
        played = [m for m in new if m.video][0]
        new, cq = await u.press(played, "O‘chirish")
        self.assertTrue(played.deleted)
        pl2 = (await u.say("/playlist"))[0]
        self.assertNotIn("1. ", pl2.text)

    async def test_photo_and_album(self):
        u = self.env.client(13)
        new = await u.say("https://www.pinterest.com/pin/photo123/")
        ph = [m for m in new if m.photo][0]
        self.assertFalse(any("Qo'shiqni" in b.text for b in ph.reply_markup.flat()), "rasmda audio tugmasi yo'q")
        new = await u.say("https://www.instagram.com/p/album1/")
        grp = [m for m in new if m.photo or m.video]
        self.assertEqual(len(grp), 10)
        self.assertIsNotNone(grp[0].caption)
        self.assertIsNone(grp[1].caption)
        await self.app.db.set_setting("max_playlist_items", "3")
        new = await u.say("https://www.instagram.com/p/album2/")
        self.assertEqual(len([m for m in new if m.photo or m.video]), 3)

    async def test_multiple_links_in_one_message(self):
        u = self.env.client(14)
        new = await u.say(f"mana {IG} va https://www.tiktok.com/@a/video/111 hamda https://youtu.be/abcdefghijk")
        self.assertEqual(len([m for m in new if m.video]), 3)

    async def test_errors_login_private_unsupported(self):
        u = self.env.client(15)
        for url in ("https://www.instagram.com/reel/login1/", "https://www.instagram.com/reel/private1/",
                    "https://example.com/unsupported"):
            before = len(u.msgs())
            await u.say(url)
            self.assertTrue(any("Yuklab bo‘lmadi" in t for t in u.texts()[before:]), url)
        # admin (owner) cookies haqida ogohlantirildi (bir marta)
        warns = [m for m in self.bot.outbox if m.chat.id == 1000 and "Cookies" in (m.text or "")]
        self.assertEqual(len(warns), 1, "ogohlantirish 30 daqiqada bir marta")
        s = await self.app.db.stats_summary()
        self.assertEqual(s["fail_day"], 3)

    async def test_size_tiers(self):
        u = self.env.client(16)
        new = await u.say("https://www.tiktok.com/@a/video/big123")
        self.assertTrue([m for m in new if m.video], "pastroq sifatda yuborilishi kerak")
        fmts = [c["format"] for c in self.env.ytdlp_calls(audio=False)]
        self.assertGreaterEqual(len(fmts), 2)
        self.assertIn("1080", fmts[0])
        new = await u.say("https://www.tiktok.com/@a/video/huge123")
        self.assertTrue(any("juda katta" in (m.text or "") for m in new))
        new = await u.say("https://www.tiktok.com/@a/video/bigraise123")
        self.assertTrue([m for m in new if m.video])

    async def test_youtube_starts_at_720(self):
        await self.env.client(17).say("https://youtu.be/abcdefghijk")
        self.assertIn("720", self.env.ytdlp_calls(audio=False)[0]["format"])

    async def test_cookies_used_per_platform(self):
        self.app.media.cookie_path("instagram").write_text("# Netscape HTTP Cookie File\n" + "a\t" * 6 + "b\n")
        await self.env.client(18).say(IG)
        await self.env.client(18).say("https://www.tiktok.com/@a/video/999")
        calls = self.env.ytdlp_calls(audio=False)
        self.assertIsNotNone(calls[0]["cookiefile"])
        self.assertIsNone(calls[1]["cookiefile"])

    async def test_group_behaviour(self):
        u = self.env.client(19)
        grp = fg.Chat(-100500, "supergroup")
        self.assertEqual(await u.say("salom hammaga", chat=grp), [], "guruhda oddiy matn e'tiborsiz")
        self.assertEqual(await u.say("https://example.com/unsupported", chat=grp), [], "noma'lum havola e'tiborsiz")
        await u.say(IG, chat=grp)
        self.assertTrue([m for m in self.bot.outbox if m.chat.id == grp.id and m.video])
        self.assertIsNone(await self.app.db.get_user(19), "guruh foydalanuvchisi 'users' ga yozilmaydi")
        await u.say("/start", chat=grp)
        self.assertTrue([m for m in self.bot.outbox if m.chat.id == grp.id and m.text])

    async def test_cobalt_fallback(self):
        await self.app.db.set_setting("cobalt_url", "http://cobalt.test/")
        fg.ClientSession.routes = {
            ("POST", "http://cobalt.test/"): fg.FakeResp(payload={"status": "tunnel", "url": "http://cdn.test/f.mp4",
                                                                 "filename": "f.mp4"}),
            ("GET", "http://cdn.test/"): fg.FakeResp(body=b"V" * 50_000),
        }
        new = await self.env.client(20).say("https://www.instagram.com/reel/boom1/")
        self.assertTrue([m for m in new if m.video], "yt-dlp yiqilganda cobalt ishlashi kerak")
        fg.ClientSession.routes = {
            ("POST", "http://cobalt.test/"): fg.FakeResp(payload={"status": "picker", "picker": [
                {"type": "photo", "url": "http://cdn.test/1.jpg"}, {"type": "photo", "url": "http://cdn.test/2.jpg"}]}),
            ("GET", "http://cdn.test/"): fg.FakeResp(body=b"J" * 20_000),
        }
        new = await self.env.client(20).say("https://www.instagram.com/p/boom2/")
        self.assertEqual(len([m for m in new if m.photo]), 2)

    async def test_pinterest_og_image_fallback(self):
        fg.ClientSession.routes = {
            ("GET", "https://www.pinterest.com/pin/boom9"): fg.FakeResp(
                payload='<meta property="og:image" content="https://i.pinimg.com/736x/ab/cd.jpg">'),
            ("GET", "https://i.pinimg.com/originals/"): fg.FakeResp(body=b"I" * 10_000),
        }
        new = await self.env.client(21).say("https://www.pinterest.com/pin/boom9")
        self.assertTrue([m for m in new if m.photo])

    # ---------------------------------------------------------------- Shazam
    async def test_shazam_voice_audio_video(self):
        u = self.env.client(30)
        for kind in ("voice", "audio", "video", "video_note"):
            new = await u.send_media(kind)
            self.assertTrue(any("Gulsanam Mamazoitova" in (m.text or "") for m in new), kind)
        self.assertEqual(fg.FakeShazam.calls, 4)

    async def test_shazam_not_found_and_failure_and_big(self):
        u = self.env.client(31)
        fg.FakeShazam.recognize_result = {}
        new = await u.send_media("voice")
        self.assertTrue(any("aniqlanmadi" in (m.text or "") for m in new))
        fg.FakeShazam.recognize_result = {"track": {"title": "T", "subtitle": "A", "key": "1"}}
        fg.FakeShazam.fail = True
        new = await u.send_media("voice")
        self.assertTrue(any("aniqlanmadi" in (m.text or "") for m in new))
        fg.FakeShazam.fail = False
        new = await u.send_media("voice", size=30 * 1024 * 1024)
        self.assertTrue(any("juda katta" in (m.text or "") for m in new))
        fg.FakeShazam.recognize_result = {"track": {"title": "Onam chiroyli", "subtitle": "Gulsanam Mamazoitova",
                                                    "key": "1"}}

    # ---------------------------------------------------------------- like / playlist / effekt
    async def test_like_playlist_flow(self):
        u = self.env.client(40)
        self.assertIn("bo‘sh", (await u.say("/my"))[0].text)
        res = (await u.say("test song"))[0]
        new, _ = await u.press_data(res, res.reply_markup.flat()[1].callback_data)
        audio = [m for m in new if m.audio][0]
        _, cq = await u.press(audio, "❤️/💔")
        self.assertIn("qo‘shildi", cq.answers[-1][0])
        pl = (await u.say("/my"))[0]
        self.assertIn("Playlist</b> (1)", pl.text)
        new, _ = await u.press_data(pl, pl.reply_markup.flat()[0].callback_data)
        self.assertTrue([m for m in new if m.audio], "playlistdan audio yuborilishi kerak")
        _, cq = await u.press(audio, "❤️/💔")
        self.assertIn("olib tashlandi", cq.answers[-1][0])
        self.assertIn("bo‘sh", (await u.say("/my"))[0].text)

    async def test_playlist_pagination(self):
        u = self.env.client(41)
        for i in range(23):
            await self.app.db.like_toggle(41, f"k{i}", f"T{i}", "P", 100 + i, f"FID{i}")
            self.bot.files[f"FID{i}"] = "audio"
        pl = (await u.say("/my"))[0]
        self.assertIn("(23)", pl.text)
        self.assertEqual(len([b for b in pl.reply_markup.flat() if b.callback_data.startswith("mp:")]), 10)
        await u.press(pl, "➡️")
        await u.press(pl, "➡️")
        self.assertEqual(len([b for b in pl.reply_markup.flat() if b.callback_data.startswith("mp:")]), 3)
        self.assertIsNone(u.find(pl, "➡️"))

    @unittest.skipUnless(real_mp3(), "ffmpeg yo'q")
    async def test_audio_effects(self):
        self.bot.download_bytes = real_mp3()
        u = self.env.client(42)
        res = (await u.say("effect song"))[0]
        new, _ = await u.press_data(res, res.reply_markup.flat()[1].callback_data)
        audio = [m for m in new if m.audio][0]
        await u.press(audio, "🎛")
        self.assertIsNotNone(u.find(audio, "Bass"))
        for label in ("Bass", "Tezlashtirilgan", "Slowed", "8D"):
            await u.press(audio, "🎛") if u.find(audio, "🎛") else None
            new, _ = await u.press(audio, label)
            self.assertTrue([m for m in new if m.audio], f"{label} effekti audio qaytarishi kerak")
        # ortga tugmasi
        await u.press(audio, "🎛")
        await u.press(audio, "Ortga")
        self.assertIsNotNone(u.find(audio, "🎛"))

    async def test_audio_effect_broken_file_reports_error(self):
        self.bot.download_bytes = b"not audio at all"
        u = self.env.client(43)
        res = (await u.say("effect song 2"))[0]
        new, _ = await u.press_data(res, res.reply_markup.flat()[1].callback_data)
        audio = [m for m in new if m.audio][0]
        await u.press(audio, "🎛")
        new, _ = await u.press(audio, "Bass")
        self.assertTrue(any("Yuklab bo‘lmadi" in (m.text or "") for m in new))

    # ---------------------------------------------------------------- top / new
    async def test_top_and_new(self):
        u = self.env.client(50)
        top = (await u.say("/top"))[0]
        flags = [b for b in top.reply_markup.flat() if b.callback_data.startswith("ch:t:") and b.callback_data.endswith(":0")
                 and len(b.text) <= 6]
        self.assertEqual(len(flags), 6)
        self.assertEqual(len([b for b in top.reply_markup.flat() if b.callback_data.startswith("cs:")]), 10)
        await u.press_data(top, "ch:t:RU:0")
        self.assertTrue(any("✅" in b.text for b in top.reply_markup.flat()))
        await u.press(top, "➡️")
        new, _ = await u.press_data(top, "cs:t:RU:12")
        self.assertTrue([m for m in new if m.audio])
        new_ = (await u.say("/new"))[0]
        self.assertEqual(new_.text, "NEW Popular Songs")
        new, _ = await u.press_data(new_, "cs:n:UZ:0")
        self.assertTrue([m for m in new if m.audio])

    async def test_top_fallback_when_shazam_down(self):
        fg.FakeShazam.fail = True
        top = (await self.env.client(51).say("/top"))[0]
        self.assertEqual(top.text, "TOP Popular Songs", "Shazam ishlamasa ham ro'yxat chiqishi kerak")
        self.assertTrue([b for b in top.reply_markup.flat() if b.callback_data.startswith("cs:")])

    # ---------------------------------------------------------------- sozlamalar
    async def test_settings(self):
        u = self.env.client(60)
        st = (await u.say("/settings"))[0]
        self.assertIn("Sozlamalar", st.text)
        await u.press(st, "Til")
        await u.press(st, "Русский")
        self.assertIn("Настройки", st.text)
        await u.press(st, "Viloyat")
        await u.press(st, "Farg'ona")
        self.assertIn("Farg", st.text)
        self.assertEqual((await self.app.db.get_user(60))["region"], "Farg'ona")
        st = (await u.say("/settings"))[0]
        await u.press(st, "Mavzu")
        await u.press(st, "Warm Autumn")
        self.assertTrue(st.text.startswith("⚙️"))
        res = (await u.say("test"))[0]
        self.assertTrue(res.text.startswith("🍂"), "mavzu natija sarlavhasiga ta'sir qilishi kerak")
        await u.press(st, "Yopish")
        self.assertTrue(st.deleted)
        # ruscha start
        self.assertIn("Здравствуйте", (await u.say("/start"))[0].text)

    async def test_user_blocks_bot(self):
        u = self.env.client(61)
        await u.say("/start")
        ev = fg.ChatMemberUpdated(self.bot, u.chat, u.user, "kicked")
        await self.dp.feed(ev)
        self.assertEqual((await self.app.db.get_user(61))["active"], 0)
        await self.dp.feed(fg.ChatMemberUpdated(self.bot, u.chat, u.user, "member"))
        self.assertEqual((await self.app.db.get_user(61))["active"], 1)


if __name__ == "__main__":
    unittest.main()
