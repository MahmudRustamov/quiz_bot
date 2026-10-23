# Oddiy baholash va yangi natijalar

Bu yangilanish mavjud bot ustiga qo‘shilgan. Eski testlar, savollar, javoblar, baholash yozuvlari, xom balllar va Rasch jadvallari saqlanadi. Standart rejim `simple`; unda theta, Z, T va sertifikat darajalari hisoblanmaydi/ko‘rsatilmaydi. Bir o‘quvchining o‘zi ham testdan keyin natija olishi mumkin.

## macOS’da yangilab ishga tushirish

Oldingi botni terminalda `Ctrl+C` bilan to‘xtating. Keyin:

```sh
cd /Users/mahmud/Developer/Bots/quiz_bot
source .venv/bin/activate
alembic upgrade head
python -m quizbot
```

Docker yoki AI API kerak emas. Avvalgi `.env` saqlanadi. Kerak bo‘lsa, quyidagi qiymatlar bilan aniq sozlang:

```dotenv
GRADING_STRATEGY=simple
SIMPLE_RELEASE_POLICY=immediate
REPORT_TIMEZONE=Asia/Tashkent
RESULTS_DIR=results
```

`d831abf20977` migratsiyasi mavjud `users`, `exams`, `attempts` jadvallariga maydonlar qo‘shadi. U tarixiy javoblar yoki xom balllarni o‘zgartirmaydi. Yangi bir xil vazifali jadvallar kiritilmagan.

## Nimalar ko‘rsatiladi

- **Savollar:** to‘g‘ri, xato, qisman to‘g‘ri, javobsiz; jami ota savollar soni.
- **Javob elementlari:** to‘g‘ri, xato, javobsiz; jami elementlar soni.
- **Foiz:** barcha zarur qismlari to‘g‘ri bo‘lgan ota savollar / jami ota savollar × 100.
- **Xom ball:** individual baholash yozuvlaridagi ballar yig‘indisi. Maksimum — qismlarning sozlangan vaznlari yig‘indisi.

44 savolli testda 40–44-savollarning A/B qismlari sabab jami 49 ta element bor. A to‘g‘ri, B xato yoki javobsiz bo‘lsa, savol qisman to‘g‘ri hisoblanadi. Ikkalasi javobsiz bo‘lsa, savol javobsiz. Bitta qism xato, ikkinchisi javobsiz bo‘lsa, savol xato. Hali tekshirilmagan qism bo‘lsa, butun natija “Tekshirilmoqda”.

Masalan, vazni 14 bo‘lgan bitta savol va ikki qismli savolning bitta qismi to‘g‘ri bajarilsa, xom ball 15 chiqishi mumkin. Bu 15 ta to‘g‘ri savol degani emas. Foiz xom balldan hisoblanmaydi. Savol va element hisoblagichlari bevosita saqlangan javoblar hamda individual baholash yozuvlaridan olinadi.

## Natijani ochish

Standart `immediate` siyosati avtomatik tekshirilgan natijani topshirish zahoti chiqaradi. Qo‘lda tekshirish kerak bo‘lsa, barcha baholar tugaguncha natija/kalitlar yopiq turadi.

Administrator misollari, test raqami `4` bo‘lganda:

```text
/resultpolicy 4 immediate on
/resultpolicy 4 manual on
/resultpolicy 4 manual off
/release 4
```

`immediate` — natija tayyor bo‘lishi bilan ochiladi. `manual` — administrator `/release 4` yuborishini kutadi. `on` — topshirilib, natijasi ochilgan urinishda javoblarni ko‘rish mumkin; `off` — javoblar sharhi yopiq. Administrator oldindan natijani e’lon qilgan bo‘lsa ham, tekshirilmagan yozma javoblar ko‘rinmaydi; tekshiruv tugashi kutiladi. Avval ochilgan natija faqat siyosatni `manual`ga almashtirish bilan yashirilmaydi.

Oddiy natijalar `simple_results_released` va `simple_released_at` bilan boshqariladi. Rasch uchun oldindan mavjud `results_released` va `released_run_id` alohida qoladi. Kalibrlash holati `unavailable` bo‘lishi oddiy natijaga to‘sqinlik qilmaydi. E’lon qilingan individual baholar qayta yozilmaydi.

## Telegram ko‘rinishi

Natija o‘quvchining haqiqiy ismi, familiyasi, fan, test nomi, savollar hisoblagichlari, foiz, xom ball va elementlar statistikasi bilan HTML shaklida chiqariladi. Kiritilgan matnlar HTML uchun xavfsizlanadi.

Tugmalar:

- ❌ Xato javoblarni ko‘rish — faqat haqiqatan xato tekshirilgan elementlar.
- ✅ To‘g‘ri javoblarni ko‘rish — to‘g‘ri elementlar.
- 🏠 Bosh menyu.

Sharhda savolning to‘liq matni/variantlari, o‘quvchi javobi, to‘g‘ri javob va mavjud tushuntirish bor. 40–44-savollar qismlari alohida ko‘rsatiladi. Oldingi/keyingi/natijaga qaytish tugmalari, asl rasm va o‘qish matniga kirish saqlanadi. Uzun HTML matnlar teglarga zarar bermasdan Telegram limitiga mos bo‘linadi. O‘quvchi boshqa odamning urinishini, uning materiali yoki natijasini ocholmaydi.

## Ism-familiya

Yangi o‘quvchidan `/start` orqali avval ism, keyin familiya so‘raladi. Telegram profil nomi avtomatik qabul qilinmaydi. `users.first_name`, `last_name`, avvalgi `full_name`, Telegram ID va dastlabki `created_at` saqlanadi.

Eski o‘quvchilarning ismini taxminan bo‘lib yuborish o‘rniga, yangi maydonlar to‘ldirilmagan bo‘lsa `/start`/Profil orqali tasdiqlash so‘raladi. Ism o‘zgarsa ham dastlabki ro‘yxatdan o‘tish vaqti va avvalgi urinishlar saqlanadi.

Fan hali ko‘rsatilmagan eski test uchun:

```text
/subject 4 Ona tili va adabiyot
```

## Administrator statistikasi va Excel

`/stats 4` endi JSON bermaydi: ishtirokchilar, topshirilgan ishlar, tekshirilayotganlar, o‘rtacha foiz va xom ballni formatlangan xabar qilib ko‘rsatadi. Undan Excel, o‘quvchilar natijalari va savollar statistikasi ochiladi. Avvalgi boshqarish, import va qo‘lda baholash buyruqlari saqlangan. `/publish` kabi buyruqqa raqam yozilmasa, kerakli namuna ko‘rsatiladi.

```text
/report 4 xlsx
```

Fayl `results/exam_4_results.xlsx` sifatida saqlanadi va faqat administratorga yuboriladi:

1. **Students:** ID, Telegram ID, ism/familiya, test, to‘g‘ri/xato/qisman/javobsiz savollar, elementlar, xom/maksimal ball, foiz, topshirish vaqti va tekshiruv holati.
2. **Individual Answers:** har bir topshirilgan urinishning har bir qismi, haqiqiy javob, kalit, to‘g‘rilik va ball.
3. **Exam Summary:** umumiy ko‘rsatkichlar, savollar statistikasi, kuzatilgan to‘liq to‘g‘ri javoblar foizi bo‘yicha qiyin/oson savollar. Bu Rasch qiyinligi emas.

O‘rtacha ball/foiz faqat tekshiruvi tugagan topshirilgan ishlardan olinadi; davom etayotgan urinishlar statistikani nol bilan pasaytirmaydi. Qisman tekshirilgan savollar bo‘yicha `pending` alohida hisoblanadi. Vaqt `Asia/Tashkent` (yoki `REPORT_TIMEZONE`) bilan, UTC farqi aniq ko‘rsatilgan ISO vaqt sifatida saqlanadi/eksport qilinadi. Bazadagi vaqtlar UTC bo‘lib qoladi. Filtrlar, ustun kengligi va muzlatilgan sarlavhalar bor; formula ko‘rinishidagi foydalanuvchi matni Excel’da bajarilmaydi. Fayl yaratish atomar, fayllar jamoatga xizmat qiluvchi URL orqali tarqatilmaydi.

## Keyingi Rasch rejimi

`SimpleGradingService`, `RaschGradingService`, `ResultPresentationService` va `ExcelExportService` alohida vazifalarni bajaradi. `GRADING_STRATEGY=rasch` bilan kelajakda avvalgi kalibrlash va versiyali nashr oqimi qayta yoqiladi. Oddiy rejimda `/calibrate` bajarilmaydi va Rasch menyusi yashiriladi. Individual javoblar, raw baholar, parametrlar va standartlashtirilgan tarixiy qiymatlar o‘chirilmaydi hamda bir-birining ustiga yozilmaydi.
