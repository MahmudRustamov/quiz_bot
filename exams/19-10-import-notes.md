# 19.10 MS mock testini yuklash

Tayyor fayl: `exams/19-10-ms-mock.json`.

44 ta ota savol, 49 ta mustaqil baholanadigan javob elementi va 3 ta umumiy o‘qish matni mavjud. Javoblar foydalanuvchi yuborgan **TEST JAVOBLARI** rasmidan ko‘chirildi. Savollar mahalliy `19.10_MS_MOCK_TEST_tahrirlangan.pdf` hujjatining barcha 15 beti bilan ko‘zdan kechirib solishtirildi. Bu davlat sertifikati yoki rasmiy vaznlar tasdig‘i emas.

## Yuklash

1. Ishlayotgan botni terminalda `Ctrl+C` bilan to‘xtating.
2. Loyiha katalogida `.venv`ni faollashtirib, yangi o‘qish matnlari jadvallarini yarating:

   ```sh
   source .venv/bin/activate
   alembic upgrade head
   python -m quizbot
   ```

3. Administrator sifatida Telegram botga `/cancel`, keyin `/import` yuboring.
4. `19-10-ms-mock.json` faylini Telegram orqali **fayl/hujjat** qilib yuboring. PDF yoki alohida savollarni yuklash kerak emas.
5. Bot qaytargan test raqamini yozib oling. Masalan, yangi raqam `3` bo‘lsa, `/publish 3` yuboring. Eski `#2` test o‘zgarishsiz qoladi.

O‘quvchi 18-, 23- yoki 28-savolga birinchi o‘tganida tegishli umumiy matn yuboriladi. Uzun matnlar bir nechta xabarga bo‘linadi. Keyingi savollarda “📖 Matnni qayta ko‘rish” tugmasi bor.

## Baholash va manbadagi izohlar

- Davomiylik **180 daqiqa** qilib belgilangan. PDFda davomiylik topilmadi; bu loyiha uchun sozlanadigan boshlang‘ich qiymat. Kerak bo‘lsa, e’lon qilishdan oldin administrator `/edit ID DAQIQA NOM` orqali o‘zgartiradi.
- Har bir javob elementi 1 xom ball, jami 49 ball. 40–44-savollar A va B qismlari alohida binary element sifatida baholanadi. Rasmiy vaznlar yoki taxminiy Rasch qiyinliklari kiritilmagan. PCM yoqilmagan.
- 3, 4, 7, 8 va 36-savollardagi chizma matnlari/o‘qlar saqlangan holda matnli shaklga o‘tkazilgan.
- 37-savol kaliti `; → :`. Bo‘shliqsiz `;→:` va ASCII o‘qli `; -> :`, `;->:` yozilishlari ham aniq ro‘yxatlangan format variantlari sifatida qabul qilinadi.
- 39-savol kaliti `o‘sha paytda men 9-sinf edim`. Faqat apostrofning `‘`, `'`, `ʻ`, `’` ko‘rinishlari uchun alohida variantlar belgilangan. Qo‘shimcha so‘z yoki erkin mazmundagi javoblar avtomatik qabul qilinmaydi.
- PDFning 14-betida 40-savolning ikkala qismi ham `a)` deb yozilgan. Ikkinchi qism javoblar rasmiga mos ravishda B deb belgilandi.
- 43-savolda tagiga chizilgan “dahr”, “shahr” so‘zlari matnda aniq ko‘rsatildi. Kalit A: `r`, B: `muqayyad`.
- 44-B uchun rasmda berilgan **Yor oydurur / yoroydurur** ikki varianti saqlandi. PDFdagi birinchi misraning tireli `yor – oydurur` yozilishi ham qabul qilinadi.
- Myunodi haqidagi matnning 7-betida “tashlana boshladi...” bilan boshlanadigan, keyin 7–8-betlarda takrorlanadigan parcha bor. U manbaga muvofiq saqlandi; o‘qish matni qisqartirilmagan.
- Savollarning o‘zidagi xato yozuvlar, masalan `daxildor`, `faravon`, `kampozitor`, `ma’orif`, `elekrton`, xato topish vazifalariga ta’sir qilmasligi uchun tahrir qilinmagan. Kalitning fan nuqtayi nazaridan to‘g‘riligi mustaqil ekspertiza sifatida da’vo qilinmaydi; kalit foydalanuvchi bergan manbadan olindi.

Ko‘chirilgan savollar `exams/source/19-10-questions.json`, kalit esa `exams/source/19-10-answer-key.json` faylida alohida saqlanadi. Matnlar ham alohida `.txt` fayllarda. Import faylini qayta yig‘ish: `python scripts/build_milliy_19_10.py`.

Natijalar mustaqil sinov baholaridir. Hozirgi standart oddiy baholashda kalibrlash yoki minimal guruh talab qilinmaydi; natija tayyor bo‘lishi bilan chiqishi mumkin. [Oddiy baholash bo‘yicha yo‘riqnoma](../docs/simple-grading.md)ga qarang. Kelajakdagi Rasch rejimi uchun avvalgi kalibrlash minimumlari saqlangan.
