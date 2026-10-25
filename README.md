# NavoBot — musiqa va video yuklovchi + Shazam (Kuy Navo uslubida)

Instagram, TikTok, YouTube, Snapchat, Likee, Pinterest, Threads, Facebook, X dan video/rasm yuklaydi,
musiqani nomi/matni/ovozi/videosi orqali topadi (Shazam), playlist, TOP/NEW reytinglar,
majburiy obuna va to'liq owner paneli (hammasi bot ichida) bor. Foydalanuvchiga limit yo'q.

## Ishga tushirish

### Docker (tavsiya)
```bash
cp .env.example .env      # BOT_TOKEN va OWNER_IDS ni to'ldiring
docker compose up -d --build
docker compose logs -f bot
```

### Oddiy Python
Python 3.11+, `ffmpeg` va `nodejs` (YouTube uchun) o'rnatilgan bo'lsin.
```bash
pip install -r requirements.txt
cp .env.example .env
python run.py
```

`OWNER_IDS` ni bilmasangiz: avval `OWNER_IDS` ni bo'sh qoldirib botni ishga tushiring, unga `/id` yozing,
chiqqan raqamni `.env` ga yozib qayta ishga tushiring.

## Owner paneli — `/admin`
| Bo'lim | Nima qiladi |
|---|---|
| 📊 Statistika | Foydalanuvchilar, yuklashlar, platformalar, viloyatlar, xatolar |
| 📢 Majburiy obuna | Kanal qo'shish (forward yoki @username), o'chirish, yoqish/o'chirish |
| 🍪 Cookies | Instagram/YouTube/... uchun cookies.txt ni botga yuborish |
| ✏️ Matnlar | Barcha matn va tugmalarni (3 tilda) tahrirlash; **premium emoji** bilan yozsangiz saqlanadi |
| 🖼 Rasmlar | /start rasmi |
| 📨 Xabar yuborish | Hammaga (matn/rasm/video), 25 xabar/soniya, bloklaganlar avtomatik belgilanadi |
| ⚙️ Sozlamalar | Caption reklamasi, albom limiti, zaxira yuklovchi (cobalt) |
| 👑 Adminlar | Qo'shimcha adminlar (faqat owner) |
| 🔄 yt-dlp | Yangilash va qayta ishga tushirish (YouTube/Instagram tez-tez o'zgaradi) |

## Muhim eslatmalar
- **Instagram/YouTube cookies**: brauzerda akkauntga kiring, «Get cookies.txt LOCALLY» kabi kengaytma bilan
  Netscape formatida eksport qiling va 🍪 Cookies orqali yuboring. Instagram uchun **alohida (asosiy emas)
  akkaunt** ishlating — ko'p so'rovda bloklanishi mumkin. Cookies eskirsa bot adminlarga xabar beradi.
- **Premium emoji**: matnlarni premium emojili holda yuborsangiz saqlanadi, lekin Telegram ularni bot
  xabarlarida faqat bot egasi Fragment orqali qo'shimcha username sotib olgan holatda ko'rsatadi
  (aks holda oddiy emoji ko'rinadi). Tugma matnlarida premium emoji ishlamaydi.
- **Fayl hajmi**: oddiy Bot API da 50 MB. Katta videolar uchun avtomatik sifat pasaytiriladi.
  To'liq 2 GB uchun `docker-compose.yml` dagi local Bot API ni yoqing.
- Cheklov yo'q, lekin bir xil havola bir vaqtda ikki marta yuklanmaydi (dublikatni oldini olish).
- Mini App (video playlist uchun veb-sahifa) hozircha yo'q: playlistlar chat ichida tugmalar bilan ishlaydi.
- Yuklash faqat o'zingiz ruxsat huquqiga ega yoki ommaviy kontent uchun; mualliflik huquqi
  uchun javobgarlik bot egasida.

## Tuzilma
```
bot/main.py          ishga tushirish
bot/handlers/user.py foydalanuvchi qismi
bot/handlers/owner.py owner paneli
bot/services/        media (yt-dlp, ffmpeg), shazam, majburiy obuna
bot/db.py            SQLite
bot/texts.py         standart matnlar va tahrir tizimi
```

## Railway'da joylash
1. Zip ichidagi **butun** `navobot` papka tarkibini GitHub repoga yuklang (ildizda `bot/` papkasi, `run.py`,
   `Dockerfile`, `requirements.txt` bo'lsin; `bot/` ichidagi fayllarni ildizga **chiqarmang**).
2. Railway `Dockerfile` ni o'zi topib ishlatadi (ffmpeg va nodejs shu bilan o'rnatiladi). Start Command bo'sh qolsin
   yoki `python run.py`.
3. Variables: `BOT_TOKEN`, `OWNER_IDS`, `DATA_DIR=/data`.
4. Volumes: `/data` ga volume ulang, aks holda har deployda baza va cookies o'chib ketadi.
