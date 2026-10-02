"""Builds backend/app/locales/<lang>.json (client-facing texts: bot, client page, status page).
Each entry: Russian source -> (en, uk, az, uz, kk, tr). Placeholders {name} and HTML tags must be kept.
Run: python backend/scripts/make_locales.py  (checks that every key used in the code has a translation)."""
import ast
import json
import re
from pathlib import Path

# only English besides the Russian source (other languages were dropped; their columns are kept for reference)
LANGS = ["en"]
ALL = ["en", "uk", "az", "uz", "kk", "tr"]
APP = Path(__file__).resolve().parent.parent / "app"

T = {
    "💳 <b>Выберите тариф</b>": (
        "💳 <b>Choose a plan</b>", "💳 <b>Оберіть тариф</b>", "💳 <b>Tarif seçin</b>", "💳 <b>Tarifni tanlang</b>",
        "💳 <b>Тарифті таңдаңыз</b>", "💳 <b>Bir tarife seçin</b>"),
    "Счёт устарел — создайте новый в боте.": (
        "The invoice has expired — create a new one in the bot.", "Рахунок застарів — створіть новий у боті.",
        "Hesab köhnəlib — botda yenisini yaradın.", "Hisob eskirgan — botda yangisini yarating.",
        "Шот ескірді — ботта жаңасын жасаңыз.", "Fatura süresi doldu — botta yenisini oluşturun."),
    "✅ Узнал вас: <b>{name}</b>. Telegram привязан — буду присылать напоминания об оплате и остатке трафика.": (
        "✅ Got you: <b>{name}</b>. Telegram is linked — I'll send reminders about payment and remaining traffic.",
        "✅ Упізнав вас: <b>{name}</b>. Telegram прив'язано — надсилатиму нагадування про оплату й залишок трафіку.",
        "✅ Sizi tanıdım: <b>{name}</b>. Telegram bağlandı — ödəniş və qalan trafik barədə xatırlatmalar göndərəcəyəm.",
        "✅ Sizni tanidim: <b>{name}</b>. Telegram bogʻlandi — toʻlov va qolgan trafik haqida eslatmalar yuboraman.",
        "✅ Сізді таныдым: <b>{name}</b>. Telegram байланыстырылды — төлем және қалған трафик туралы еске салып отырамын.",
        "✅ Sizi tanıdım: <b>{name}</b>. Telegram bağlandı — ödeme ve kalan trafik hakkında hatırlatmalar göndereceğim."),
    "Запрос отправлен администратору — как только он подтвердит, я пришлю вашу ссылку. Быстрее всего — прислать сюда свою ссылку-подписку или ключ из приложения.": (
        "The request has been sent to the administrator — as soon as they confirm, I'll send your link. The fastest way is to send your subscription link or a key from the app here.",
        "Запит надіслано адміністратору — щойно він підтвердить, я надішлю ваше посилання. Найшвидше — надіслати сюди посилання-підписку або ключ із застосунку.",
        "Sorğu administratora göndərildi — təsdiqləyən kimi linkinizi göndərəcəyəm. Ən sürətli yol — abunə linkinizi və ya tətbiqdən açarı bura göndərməkdir.",
        "Soʻrov administratorga yuborildi — tasdiqlashi bilan havolangizni yuboraman. Eng tezi — obuna havolangizni yoki ilovadagi kalitni shu yerga yuboring.",
        "Сұрау әкімшіге жіберілді — ол растағанда сілтемеңізді жіберемін. Ең жылдамы — жазылым сілтемесін немесе қолданбадағы кілтті осында жіберу.",
        "İstek yöneticiye gönderildi — onaylar onaylamaz bağlantınızı göndereceğim. En hızlısı abonelik bağlantınızı veya uygulamadaki anahtarı buraya göndermek."),
    "Не нашёл аккаунт по этой ссылке. Пришлите ссылку-подписку целиком (в приложении: профиль → поделиться / копировать) или ключ vless://…": (
        "I couldn't find an account for this link. Send the whole subscription link (in the app: profile → share / copy) or a vless://… key",
        "Не знайшов акаунт за цим посиланням. Надішліть посилання-підписку повністю (у застосунку: профіль → поділитися / копіювати) або ключ vless://…",
        "Bu linkə görə hesab tapılmadı. Abunə linkini tam göndərin (tətbiqdə: profil → paylaş / kopyala) və ya vless://… açarını.",
        "Bu havola boʻyicha akkaunt topilmadi. Obuna havolasini toʻliq yuboring (ilovada: profil → ulashish / nusxalash) yoki vless://… kalitini.",
        "Бұл сілтеме бойынша аккаунт табылмады. Жазылым сілтемесін толық жіберіңіз (қолданбада: профиль → бөлісу / көшіру) немесе vless://… кілтін.",
        "Bu bağlantıya ait hesap bulunamadı. Abonelik bağlantısının tamamını (uygulamada: profil → paylaş / kopyala) veya vless://… anahtarını gönderin."),
    "{n} ГБ": ("{n} GB", "{n} ГБ", "{n} GB", "{n} GB", "{n} ГБ", "{n} GB"),
    "безлимит": ("unlimited", "безліміт", "limitsiz", "cheksiz", "шексіз", "sınırsız"),
    "Способ оплаты:": ("Payment method:", "Спосіб оплати:", "Ödəniş üsulu:", "Toʻlov usuli:", "Төлем тәсілі:", "Ödeme yöntemi:"),
    "Спасибо! Администратор проверит поступление и подтвердит — я сразу напишу.": (
        "Thank you! The administrator will check the payment and confirm — I'll message you right away.",
        "Дякуємо! Адміністратор перевірить надходження й підтвердить — я одразу напишу.",
        "Təşəkkürlər! Administrator ödənişi yoxlayıb təsdiqləyəcək — dərhal yazacağam.",
        "Rahmat! Administrator toʻlovni tekshirib tasdiqlaydi — darhol yozaman.",
        "Рахмет! Әкімші төлемді тексеріп, растайды — бірден жазамын.",
        "Teşekkürler! Yönetici ödemeyi kontrol edip onaylayacak — hemen yazacağım."),
    "🤝 <b>Пригласите друга</b>\n\nКогда друг оплатит подписку, вы получите <b>+{bonus} дн.</b>, а он — <b>+{friend} дн.</b> в подарок.\n\nВаша ссылка:\n{link}\n\nПриглашено: {invited}, оплатили: {paid}": (
        "🤝 <b>Invite a friend</b>\n\nWhen your friend pays for a subscription, you get <b>+{bonus} days</b> and they get <b>+{friend} days</b> as a gift.\n\nYour link:\n{link}\n\nInvited: {invited}, paid: {paid}",
        "🤝 <b>Запросіть друга</b>\n\nКоли друг оплатить підписку, ви отримаєте <b>+{bonus} дн.</b>, а він — <b>+{friend} дн.</b> у подарунок.\n\nВаше посилання:\n{link}\n\nЗапрошено: {invited}, оплатили: {paid}",
        "🤝 <b>Dostunuzu dəvət edin</b>\n\nDostunuz abunəni ödəyəndə siz <b>+{bonus} gün</b>, o isə hədiyyə olaraq <b>+{friend} gün</b> alacaq.\n\nLinkiniz:\n{link}\n\nDəvət edilib: {invited}, ödəyib: {paid}",
        "🤝 <b>Doʻstingizni taklif qiling</b>\n\nDoʻstingiz obunani toʻlaganda siz <b>+{bonus} kun</b>, u esa sovgʻa sifatida <b>+{friend} kun</b> oladi.\n\nHavolangiz:\n{link}\n\nTaklif qilingan: {invited}, toʻlagan: {paid}",
        "🤝 <b>Досыңызды шақырыңыз</b>\n\nДосыңыз жазылымды төлегенде сіз <b>+{bonus} күн</b>, ал ол сыйлыққа <b>+{friend} күн</b> алады.\n\nСіздің сілтемеңіз:\n{link}\n\nШақырылды: {invited}, төледі: {paid}",
        "🤝 <b>Bir arkadaşını davet et</b>\n\nArkadaşın aboneliği ödediğinde sen <b>+{bonus} gün</b>, o da hediye olarak <b>+{friend} gün</b> alır.\n\nBağlantın:\n{link}\n\nDavet edilen: {invited}, ödeyen: {paid}"),
    "🤝 Пригласить друга": ("🤝 Invite a friend", "🤝 Запросити друга", "🤝 Dost dəvət et", "🤝 Doʻst taklif qilish", "🤝 Дос шақыру", "🤝 Arkadaş davet et"),
    "🎟 Промокод": ("🎟 Promo code", "🎟 Промокод", "🎟 Promokod", "🎟 Promokod", "🎟 Промокод", "🎟 Promosyon kodu"),
    "Язык": ("Language", "Мова", "Dil", "Til", "Тіл", "Dil"),
    "💬 Поддержка": ("💬 Support", "💬 Підтримка", "💬 Dəstək", "💬 Yordam", "💬 Қолдау", "💬 Destek"),
    "Если у вас уже есть доступ — пришлите сюда ссылку-подписку или ключ из приложения, и я привяжу аккаунт.": (
        "If you already have access, send your subscription link or a key from the app here and I'll link your account.",
        "Якщо у вас уже є доступ — надішліть сюди посилання-підписку або ключ із застосунку, і я прив'яжу акаунт.",
        "Artıq girişiniz varsa, abunə linkini və ya tətbiqdən açarı bura göndərin — hesabı bağlayacağam.",
        "Agar sizda allaqachon kirish boʻlsa, obuna havolasi yoki ilovadagi kalitni shu yerga yuboring — akkauntni bogʻlayman.",
        "Егер сізде қолжетімділік бар болса, жазылым сілтемесін немесе қолданбадағы кілтті осында жіберіңіз — аккаунтты байланыстырамын.",
        "Zaten erişiminiz varsa abonelik bağlantınızı veya uygulamadaki anahtarı buraya gönderin, hesabı bağlayayım."),
    "Онлайн-оплата пока не подключена — напишите в поддержку.": (
        "Online payment isn't available yet — please contact support.", "Онлайн-оплату ще не підключено — напишіть у підтримку.",
        "Onlayn ödəniş hələ qoşulmayıb — dəstəyə yazın.", "Onlayn toʻlov hali ulanmagan — yordamga yozing.",
        "Онлайн төлем әлі қосылмаған — қолдау қызметіне жазыңыз.", "Çevrimiçi ödeme henüz bağlı değil — desteğe yazın."),
    " (было {old})": (" (was {old})", " (було {old})", " (əvvəl {old})", " (oldin {old})", " (бұрын {old})", " (önce {old})"),
    "Этот заказ уже обработан.": ("This order has already been processed.", "Це замовлення вже оброблено.", "Bu sifariş artıq emal olunub.",
                                  "Bu buyurtma allaqachon koʻrib chiqilgan.", "Бұл тапсырыс өңделіп қойған.", "Bu sipariş zaten işlendi."),
    "Реферальная программа сейчас не действует.": (
        "The referral program isn't active right now.", "Реферальна програма зараз не діє.", "Referal proqramı hazırda aktiv deyil.",
        "Referal dasturi hozir ishlamayapti.", "Рефералдық бағдарлама қазір жұмыс істемейді.", "Referans programı şu anda aktif değil."),
    "Сначала привяжите аккаунт — пришлите ссылку-подписку или ключ.": (
        "Link your account first — send your subscription link or key.", "Спершу прив'яжіть акаунт — надішліть посилання-підписку або ключ.",
        "Əvvəlcə hesabı bağlayın — abunə linkini və ya açarı göndərin.", "Avval akkauntni bogʻlang — obuna havolasi yoki kalitni yuboring.",
        "Алдымен аккаунтты байланыстырыңыз — жазылым сілтемесін немесе кілтті жіберіңіз.", "Önce hesabınızı bağlayın — abonelik bağlantınızı veya anahtarı gönderin."),
    "Укажите код: <code>/promo КОД</code>": ("Enter the code: <code>/promo CODE</code>", "Вкажіть код: <code>/promo КОД</code>",
                                            "Kodu yazın: <code>/promo KOD</code>", "Kodni kiriting: <code>/promo KOD</code>",
                                            "Кодты жазыңыз: <code>/promo КОД</code>", "Kodu yazın: <code>/promo KOD</code>"),
    "📲 Подключить": ("📲 Connect", "📲 Підключити", "📲 Qoşul", "📲 Ulanish", "📲 Қосылу", "📲 Bağlan"),
    "📊 Статус": ("📊 Status", "📊 Статус", "📊 Status", "📊 Holat", "📊 Күйі", "📊 Durum"),
    "🎁 Пробный период": ("🎁 Free trial", "🎁 Пробний період", "🎁 Sınaq müddəti", "🎁 Sinov davri", "🎁 Сынақ мерзімі", "🎁 Deneme süresi"),
    ", семья до {n}": (", family up to {n}", ", сім'я до {n}", ", ailə {n} nəfərədək", ", oila {n} kishigacha", ", отбасы {n} адамға дейін", ", aile {n} kişiye kadar"),
    "🧾 <b>Оплата переводом</b>": ("🧾 <b>Bank transfer</b>", "🧾 <b>Оплата переказом</b>", "🧾 <b>Köçürmə ilə ödəniş</b>",
                                 "🧾 <b>Oʻtkazma orqali toʻlov</b>", "🧾 <b>Аударыммен төлеу</b>", "🧾 <b>Havale ile ödeme</b>"),
    "⭐ К оплате: <b>{stars} звёзд</b> ({amount} ₽).": (
        "⭐ To pay: <b>{stars} stars</b> ({amount} ₽).", "⭐ До сплати: <b>{stars} зірок</b> ({amount} ₽).",
        "⭐ Ödəniləcək: <b>{stars} ulduz</b> ({amount} ₽).", "⭐ Toʻlov: <b>{stars} yulduz</b> ({amount} ₽).",
        "⭐ Төлеуге: <b>{stars} жұлдыз</b> ({amount} ₽).", "⭐ Ödenecek: <b>{stars} yıldız</b> ({amount} ₽)."),
    "🧾 Счёт на <b>{amount} ₽</b> создан. После оплаты доступ продлится автоматически, я пришлю подтверждение.": (
        "🧾 An invoice for <b>{amount} ₽</b> has been created. After payment your access is extended automatically and I'll send a confirmation.",
        "🧾 Рахунок на <b>{amount} ₽</b> створено. Після оплати доступ продовжиться автоматично, я надішлю підтвердження.",
        "🧾 <b>{amount} ₽</b> məbləğində hesab yaradıldı. Ödənişdən sonra giriş avtomatik uzadılacaq, təsdiq göndərəcəyəm.",
        "🧾 <b>{amount} ₽</b> hisob yaratildi. Toʻlovdan soʻng kirish avtomatik uzaytiriladi, tasdiq yuboraman.",
        "🧾 <b>{amount} ₽</b> шот жасалды. Төлемнен кейін қолжетімділік автоматты түрде ұзартылады, растау жіберемін.",
        "🧾 <b>{amount} ₽</b> tutarında fatura oluşturuldu. Ödemeden sonra erişim otomatik uzatılır, onay göndereceğim."),
    "✅ Язык: русский": ("✅ Language: English", "✅ Мова: українська", "✅ Dil: Azərbaycan dili", "✅ Til: oʻzbekcha",
                         "✅ Тіл: қазақша", "✅ Dil: Türkçe"),
    "💳 Оплатить / продлить": ("💳 Pay / extend", "💳 Оплатити / продовжити", "💳 Ödə / uzat", "💳 Toʻlash / uzaytirish",
                              "💳 Төлеу / ұзарту", "💳 Öde / uzat"),
    "💳 Купить доступ": ("💳 Buy access", "💳 Купити доступ", "💳 Giriş al", "💳 Kirish sotib olish", "💳 Қолжетімділік сатып алу", "💳 Erişim satın al"),
    "✉️ Передал ваше сообщение в поддержку — ответ придёт сюда.": (
        "✉️ I've passed your message to support — the answer will come here.", "✉️ Передав ваше повідомлення в підтримку — відповідь прийде сюди.",
        "✉️ Mesajınızı dəstəyə ötürdüm — cavab bura gələcək.", "✉️ Xabaringizni yordamga yubordim — javob shu yerga keladi.",
        "✉️ Хабарламаңызды қолдау қызметіне жібердім — жауап осында келеді.", "✉️ Mesajınızı desteğe ilettim — yanıt buraya gelecek."),
    "Поддержка сейчас недоступна, попробуйте позже.": (
        "Support is unavailable right now, please try later.", "Підтримка зараз недоступна, спробуйте пізніше.",
        "Dəstək hazırda əlçatan deyil, sonra cəhd edin.", "Yordam hozir mavjud emas, keyinroq urinib koʻring.",
        "Қолдау қызметі қазір қолжетімсіз, кейінірек көріңіз.", "Destek şu anda kullanılamıyor, lütfen daha sonra deneyin."),
    "{days} дн.": ("{days} days", "{days} дн.", "{days} gün", "{days} kun", "{days} күн", "{days} gün"),
    "❌ Администратор не нашёл ваш перевод. Если это ошибка — напишите в поддержку.": (
        "❌ The administrator couldn't find your transfer. If this is a mistake, please contact support.",
        "❌ Адміністратор не знайшов ваш переказ. Якщо це помилка — напишіть у підтримку.",
        "❌ Administrator köçürmənizi tapmadı. Səhvdirsə — dəstəyə yazın.",
        "❌ Administrator oʻtkazmangizni topmadi. Agar bu xato boʻlsa — yordamga yozing.",
        "❌ Әкімші аударымыңызды таппады. Егер бұл қате болса — қолдау қызметіне жазыңыз.",
        "❌ Yönetici havalenizi bulamadı. Bir hata olduğunu düşünüyorsanız desteğe yazın."),
    "Аккаунт не найден.": ("Account not found.", "Акаунт не знайдено.", "Hesab tapılmadı.", "Akkaunt topilmadi.", "Аккаунт табылмады.", "Hesap bulunamadı."),
    "✅ Я оплатил": ("✅ I've paid", "✅ Я оплатив", "✅ Ödədim", "✅ Toʻladim", "✅ Төледім", "✅ Ödedim"),
    "Оплатить {stars} ⭐": ("Pay {stars} ⭐", "Сплатити {stars} ⭐", "{stars} ⭐ ödə", "{stars} ⭐ toʻlash", "{stars} ⭐ төлеу", "{stars} ⭐ öde"),
    "💳 Оплатить {amount} ₽": ("💳 Pay {amount} ₽", "💳 Сплатити {amount} ₽", "💳 {amount} ₽ ödə", "💳 {amount} ₽ toʻlash", "💳 {amount} ₽ төлеу", "💳 {amount} ₽ öde"),
    "🎟 Отправьте промокод командой: <code>/promo КОД</code>": (
        "🎟 Send the promo code with the command: <code>/promo CODE</code>", "🎟 Надішліть промокод командою: <code>/promo КОД</code>",
        "🎟 Promokodu əmrlə göndərin: <code>/promo KOD</code>", "🎟 Promokodni buyruq bilan yuboring: <code>/promo KOD</code>",
        "🎟 Промокодты командамен жіберіңіз: <code>/promo КОД</code>", "🎟 Promosyon kodunu komutla gönderin: <code>/promo KOD</code>"),
    "💬 Напишите вопрос одним сообщением — я передам его в поддержку, ответ придёт сюда.": (
        "💬 Write your question in one message — I'll pass it to support and the answer will come here.",
        "💬 Напишіть питання одним повідомленням — я передам його в підтримку, відповідь прийде сюди.",
        "💬 Sualınızı bir mesajla yazın — dəstəyə ötürəcəyəm, cavab bura gələcək.",
        "💬 Savolingizni bitta xabarda yozing — yordamga yuboraman, javob shu yerga keladi.",
        "💬 Сұрағыңызды бір хабарламамен жазыңыз — қолдау қызметіне жіберемін, жауап осында келеді.",
        "💬 Sorunuzu tek mesajda yazın — desteğe ileteceğim, yanıt buraya gelecek."),
    "осталось {n} ГБ": ("{n} GB left", "залишилось {n} ГБ", "{n} GB qalıb", "{n} GB qoldi", "{n} ГБ қалды", "{n} GB kaldı"),
    "без ограничений": ("unlimited", "без обмежень", "limitsiz", "cheklovsiz", "шектеусіз", "sınırsız"),
    "осталось {days} дн.": ("{days} days left", "залишилось {days} дн.", "{days} gün qalıb", "{days} kun qoldi", "{days} күн қалды", "{days} gün kaldı"),
    "истекла": ("expired", "закінчилась", "bitib", "tugagan", "аяқталды", "sona erdi"),
    "бессрочно": ("no expiry", "безстроково", "müddətsiz", "muddatsiz", "мерзімсіз", "süresiz"),
    "Трафик": ("Traffic", "Трафік", "Trafik", "Trafik", "Трафик", "Trafik"),
    "Подписка": ("Subscription", "Підписка", "Abunə", "Obuna", "Жазылым", "Abonelik"),
    "Подключение на {device}": ("Connecting on {device}", "Підключення на {device}", "{device} üçün qoşulma", "{device} da ulanish",
                                "{device} құрылғысында қосылу", "{device} üzerinde bağlantı"),
    "Установите приложение, затем добавьте подписку в одно нажатие.": (
        "Install the app, then add the subscription in one tap.", "Встановіть застосунок, потім додайте підписку одним натисканням.",
        "Tətbiqi quraşdırın, sonra abunəni bir toxunuşla əlavə edin.", "Ilovani oʻrnating, soʻng obunani bir bosishda qoʻshing.",
        "Қолданбаны орнатыңыз, содан кейін жазылымды бір басумен қосыңыз.", "Uygulamayı yükleyin, ardından aboneliği tek dokunuşla ekleyin."),
    "На другом устройстве": ("On another device", "На іншому пристрої", "Başqa cihazda", "Boshqa qurilmada", "Басқа құрылғыда", "Başka bir cihazda"),
    "Отсканируйте QR камерой или в приложении — или скопируйте ссылку.": (
        "Scan the QR code with the camera or in the app — or copy the link.", "Відскануйте QR камерою або в застосунку — або скопіюйте посилання.",
        "QR kodu kamera ilə və ya tətbiqdə skan edin — ya da linki kopyalayın.", "QR kodni kamera yoki ilovada skanerlang — yoki havolani nusxalang.",
        "QR кодты камерамен немесе қолданбада сканерлеңіз — не сілтемені көшіріңіз.", "QR kodu kamerayla veya uygulamada tarayın — ya da bağlantıyı kopyalayın."),
    "Копировать": ("Copy", "Копіювати", "Kopyala", "Nusxalash", "Көшіру", "Kopyala"),
    "Не подключается на мобильном интернете?": ("Won't connect on mobile data?", "Не підключається на мобільному інтернеті?",
                                                "Mobil internetdə qoşulmur?", "Mobil internetda ulanmayaptimi?",
                                                "Мобильді интернетте қосылмай ма?", "Mobil internette bağlanmıyor mu?"),
    "Выберите в приложении сервер с 🛡 и пометкой «мобильный».": (
        "In the app, choose a server with 🛡 and the “mobile” label.", "Оберіть у застосунку сервер із 🛡 і позначкою «мобільний».",
        "Tətbiqdə 🛡 və «mobil» qeydi olan serveri seçin.", "Ilovada 🛡 va «mobil» belgisi boʻlgan serverni tanlang.",
        "Қолданбада 🛡 және «мобильді» белгісі бар серверді таңдаңыз.", "Uygulamada 🛡 ve “mobil” etiketli sunucuyu seçin."),
    "Выключите «Частный DNS» (Настройки → Сеть).": (
        "Turn off “Private DNS” (Settings → Network).", "Вимкніть «Приватний DNS» (Налаштування → Мережа).",
        "«Şəxsi DNS»-i söndürün (Parametrlər → Şəbəkə).", "«Shaxsiy DNS»ni oʻchiring (Sozlamalar → Tarmoq).",
        "«Жеке DNS» өшіріңіз (Параметрлер → Желі).", "“Özel DNS”i kapatın (Ayarlar → Ağ)."),
    "Обновите подписку в приложении.": ("Update the subscription in the app.", "Оновіть підписку в застосунку.", "Tətbiqdə abunəni yeniləyin.",
                                        "Ilovada obunani yangilang.", "Қолданбада жазылымды жаңартыңыз.", "Uygulamada aboneliği güncelleyin."),
    "Ручная настройка": ("Manual setup", "Ручне налаштування", "Əl ilə quraşdırma", "Qoʻlda sozlash", "Қолмен баптау", "Manuel kurulum"),
    "В приложении нажмите «+» → «Импорт из буфера» / «Добавить подписку».": (
        "In the app tap “+” → “Import from clipboard” / “Add subscription”.", "У застосунку натисніть «+» → «Імпорт із буфера» / «Додати підписку».",
        "Tətbiqdə «+» → «Buferdən idxal» / «Abunə əlavə et» düyməsinə basın.", "Ilovada «+» → «Buferdan import» / «Obuna qoʻshish»ni bosing.",
        "Қолданбада «+» → «Буферден импорттау» / «Жазылым қосу» басыңыз.", "Uygulamada “+” → “Panodan içe aktar” / “Abonelik ekle”ye dokunun."),
    "Вставьте скопированную ссылку.": ("Paste the copied link.", "Вставте скопійоване посилання.", "Kopyalanmış linki yapışdırın.",
                                       "Nusxalangan havolani joylang.", "Көшірілген сілтемені қойыңыз.", "Kopyaladığınız bağlantıyı yapıştırın."),
    "Выберите сервер и включите VPN.": ("Choose a server and turn on the VPN.", "Оберіть сервер і ввімкніть VPN.", "Server seçin və VPN-i açın.",
                                        "Serverni tanlang va VPNni yoqing.", "Серверді таңдап, VPN қосыңыз.", "Bir sunucu seçin ve VPN'i açın."),
    "Продлить подписку": ("Extend subscription", "Продовжити підписку", "Abunəni uzat", "Obunani uzaytirish", "Жазылымды ұзарту", "Aboneliği uzat"),
    "Выберите тариф и способ оплаты — доступ продлится автоматически.": (
        "Choose a plan and a payment method — your access is extended automatically.", "Оберіть тариф і спосіб оплати — доступ продовжиться автоматично.",
        "Tarif və ödəniş üsulunu seçin — giriş avtomatik uzadılacaq.", "Tarif va toʻlov usulini tanlang — kirish avtomatik uzaytiriladi.",
        "Тариф пен төлем тәсілін таңдаңыз — қолжетімділік автоматты түрде ұзартылады.", "Bir tarife ve ödeme yöntemi seçin — erişim otomatik uzatılır."),
    "Промокод": ("Promo code", "Промокод", "Promokod", "Promokod", "Промокод", "Promosyon kodu"),
    "Применить": ("Apply", "Застосувати", "Tətbiq et", "Qoʻllash", "Қолдану", "Uygula"),
    "🤝 Пригласите друга": ("🤝 Invite a friend", "🤝 Запросіть друга", "🤝 Dostunuzu dəvət edin", "🤝 Doʻstingizni taklif qiling",
                           "🤝 Досыңызды шақырыңыз", "🤝 Bir arkadaşını davet et"),
    "Друг оплатит подписку — вам +{bonus} дн., ему +{friend} дн. в подарок.": (
        "When a friend pays — you get +{bonus} days, they get +{friend} days as a gift.", "Друг оплатить підписку — вам +{bonus} дн., йому +{friend} дн. у подарунок.",
        "Dostunuz ödəyəndə — sizə +{bonus} gün, ona hədiyyə +{friend} gün.", "Doʻstingiz toʻlasa — sizga +{bonus} kun, unga sovgʻa +{friend} kun.",
        "Досыңыз төлесе — сізге +{bonus} күн, оған сыйлыққа +{friend} күн.", "Arkadaşın ödediğinde — sana +{bonus} gün, ona hediye +{friend} gün."),
    "Поделиться": ("Share", "Поділитися", "Paylaş", "Ulashish", "Бөлісу", "Paylaş"),
    "Состояние серверов": ("Server status", "Стан серверів", "Serverlərin vəziyyəti", "Serverlar holati", "Серверлер күйі", "Sunucu durumu"),
    "Активна": ("Active", "Активна", "Aktiv", "Faol", "Белсенді", "Aktif"),
    "Срок истёк": ("Expired", "Термін минув", "Müddəti bitib", "Muddati tugagan", "Мерзімі өтті", "Süresi doldu"),
    "Трафик закончился": ("Out of traffic", "Трафік закінчився", "Trafik bitib", "Trafik tugagan", "Трафик бітті", "Trafik bitti"),
    "Отключена": ("Disabled", "Вимкнена", "Söndürülüb", "Oʻchirilgan", "Өшірілген", "Devre dışı"),
    "1. Установить": ("1. Install", "1. Встановити", "1. Quraşdır", "1. Oʻrnatish", "1. Орнату", "1. Yükle"),
    "2. Добавить подписку": ("2. Add subscription", "2. Додати підписку", "2. Abunə əlavə et", "2. Obuna qoʻshish", "2. Жазылым қосу", "2. Abonelik ekle"),
    "🔔 Получать напоминания в Telegram": ("🔔 Get reminders in Telegram", "🔔 Отримувати нагадування в Telegram",
                                           "🔔 Telegram-da xatırlatmalar al", "🔔 Telegramda eslatmalar olish",
                                           "🔔 Telegram-да еске салғыштар алу", "🔔 Telegram'da hatırlatma al"),
    "Введите код": ("Enter the code", "Введіть код", "Kodu daxil edin", "Kodni kiriting", "Кодты енгізіңіз", "Kodu girin"),
    "рекомендуем": ("recommended", "рекомендуємо", "tövsiyə edirik", "tavsiya etamiz", "ұсынамыз", "önerilen"),
    "🎟 Промокод принят: скидка {pct}% на следующую оплату.": (
        "🎟 Promo code accepted: {pct}% off your next payment.", "🎟 Промокод прийнято: знижка {pct}% на наступну оплату.",
        "🎟 Promokod qəbul edildi: növbəti ödənişə {pct}% endirim.", "🎟 Promokod qabul qilindi: keyingi toʻlovga {pct}% chegirma.",
        "🎟 Промокод қабылданды: келесі төлемге {pct}% жеңілдік.", "🎟 Promosyon kodu kabul edildi: sonraki ödemede %{pct} indirim."),
    "🎟 Промокод принят: +{days} дн. к подписке.": (
        "🎟 Promo code accepted: +{days} days added to your subscription.", "🎟 Промокод прийнято: +{days} дн. до підписки.",
        "🎟 Promokod qəbul edildi: abunəyə +{days} gün.", "🎟 Promokod qabul qilindi: obunaga +{days} kun.",
        "🎟 Промокод қабылданды: жазылымға +{days} күн.", "🎟 Promosyon kodu kabul edildi: aboneliğe +{days} gün."),
    "🎁 Ваш друг оплатил подписку — вам +{days} дн. Спасибо!": (
        "🎁 Your friend paid for a subscription — you get +{days} days. Thank you!", "🎁 Ваш друг оплатив підписку — вам +{days} дн. Дякуємо!",
        "🎁 Dostunuz abunəni ödədi — sizə +{days} gün. Təşəkkürlər!", "🎁 Doʻstingiz obunani toʻladi — sizga +{days} kun. Rahmat!",
        "🎁 Досыңыз жазылымды төледі — сізге +{days} күн. Рахмет!", "🎁 Arkadaşın aboneliği ödedi — sana +{days} gün. Teşekkürler!"),
    "Страница обновляется каждую минуту.": ("The page refreshes every minute.", "Сторінка оновлюється щохвилини.", "Səhifə hər dəqiqə yenilənir.",
                                            "Sahifa har daqiqada yangilanadi.", "Бет әр минут сайын жаңарады.", "Sayfa her dakika yenilenir."),
    "Все серверы работают": ("All servers are up", "Усі сервери працюють", "Bütün serverlər işləyir", "Barcha serverlar ishlayapti",
                             "Барлық серверлер жұмыс істеп тұр", "Tüm sunucular çalışıyor"),
    "Есть недоступные серверы — подключайтесь через другой сервер в приложении": (
        "Some servers are down — connect through another server in the app", "Є недоступні сервери — підключайтеся через інший сервер у застосунку",
        "Əlçatmaz serverlər var — tətbiqdə başqa serverlə qoşulun", "Ishlamayotgan serverlar bor — ilovada boshqa server orqali ulaning",
        "Қолжетімсіз серверлер бар — қолданбада басқа сервер арқылы қосылыңыз", "Erişilemeyen sunucular var — uygulamada başka bir sunucu üzerinden bağlanın"),
    "30 дней · доступность": ("30 days · availability", "30 днів · доступність", "30 gün · əlçatanlıq", "30 kun · mavjudlik",
                              "30 күн · қолжетімділік", "30 gün · erişilebilirlik"),
    "работает": ("up", "працює", "işləyir", "ishlayapti", "жұмыс істейді", "çalışıyor"),
    "недоступен": ("down", "недоступний", "əlçatmazdır", "ishlamayapti", "қолжетімсіз", "erişilemiyor"),
    "нет данных": ("no data", "немає даних", "məlumat yoxdur", "maʼlumot yoʻq", "дерек жоқ", "veri yok"),
    "Сумма: {amount} ₽ · заказ №{id}": ("Amount: {amount} ₽ · order #{id}", "Сума: {amount} ₽ · замовлення №{id}",
                                         "Məbləğ: {amount} ₽ · sifariş №{id}", "Summa: {amount} ₽ · buyurtma №{id}",
                                         "Сомасы: {amount} ₽ · тапсырыс №{id}", "Tutar: {amount} ₽ · sipariş no. {id}"),
    "✅ <b>Оплата получена, спасибо!</b>": ("✅ <b>Payment received, thank you!</b>", "✅ <b>Оплату отримано, дякуємо!</b>",
                                           "✅ <b>Ödəniş alındı, təşəkkürlər!</b>", "✅ <b>Toʻlov qabul qilindi, rahmat!</b>",
                                           "✅ <b>Төлем алынды, рахмет!</b>", "✅ <b>Ödeme alındı, teşekkürler!</b>"),
    "💬 <b>Поддержка nicro</b>": ("💬 <b>nicro support</b>", "💬 <b>Підтримка nicro</b>", "💬 <b>nicro dəstəyi</b>",
                                "💬 <b>nicro yordami</b>", "💬 <b>nicro қолдауы</b>", "💬 <b>nicro destek</b>"),
    "🎁 Пробный период активирован! Ниже — как подключиться.": (
        "🎁 Free trial activated! How to connect is below.", "🎁 Пробний період активовано! Нижче — як підключитися.",
        "🎁 Sınaq müddəti aktivləşdirildi! Aşağıda — necə qoşulmaq olar.", "🎁 Sinov davri faollashtirildi! Quyida — qanday ulanish.",
        "🎁 Сынақ мерзімі іске қосылды! Төменде — қалай қосылу керек.", "🎁 Deneme süresi etkinleştirildi! Nasıl bağlanacağınız aşağıda."),
    "✅ Подписка активна": ("✅ Subscription active", "✅ Підписка активна", "✅ Abunə aktivdir", "✅ Obuna faol", "✅ Жазылым белсенді", "✅ Abonelik aktif"),
    "⛔ Подписка закончилась": ("⛔ Subscription ended", "⛔ Підписка закінчилась", "⛔ Abunə bitib", "⛔ Obuna tugadi", "⛔ Жазылым аяқталды", "⛔ Abonelik sona erdi"),
    "⛔ Трафик закончился": ("⛔ Out of traffic", "⛔ Трафік закінчився", "⛔ Trafik bitib", "⛔ Trafik tugadi", "⛔ Трафик бітті", "⛔ Trafik bitti"),
    "⛔ Доступ отключён": ("⛔ Access disabled", "⛔ Доступ вимкнено", "⛔ Giriş söndürülüb", "⛔ Kirish oʻchirilgan", "⛔ Қолжетімділік өшірілген", "⛔ Erişim devre dışı"),
    "Пробный период сейчас не выдаётся. Напишите в поддержку.": (
        "Free trials aren't available right now. Please contact support.", "Пробний період зараз не надається. Напишіть у підтримку.",
        "Sınaq müddəti hazırda verilmir. Dəstəyə yazın.", "Sinov davri hozir berilmaydi. Yordamga yozing.",
        "Сынақ мерзімі қазір берілмейді. Қолдау қызметіне жазыңыз.", "Deneme süresi şu anda verilmiyor. Desteğe yazın."),
    "У вас уже есть аккаунт — пробный период выдаётся один раз. /sub — ссылка для подключения.": (
        "You already have an account — a free trial is given only once. /sub — your connection link.",
        "У вас уже є акаунт — пробний період надається один раз. /sub — посилання для підключення.",
        "Artıq hesabınız var — sınaq müddəti bir dəfə verilir. /sub — qoşulma linki.",
        "Sizda allaqachon akkaunt bor — sinov davri bir marta beriladi. /sub — ulanish havolasi.",
        "Сізде аккаунт бар — сынақ мерзімі бір рет беріледі. /sub — қосылу сілтемесі.",
        "Zaten bir hesabınız var — deneme süresi bir kez verilir. /sub — bağlantı linkiniz."),
    "📊 Трафик: {used} из {limit} (осталось {left})": (
        "📊 Traffic: {used} of {limit} ({left} left)", "📊 Трафік: {used} з {limit} (залишилось {left})",
        "📊 Trafik: {used} / {limit} ({left} qalıb)", "📊 Trafik: {used} / {limit} ({left} qoldi)",
        "📊 Трафик: {used} / {limit} ({left} қалды)", "📊 Trafik: {used} / {limit} ({left} kaldı)"),
    "📊 Трафик: {used} (без ограничений)": ("📊 Traffic: {used} (unlimited)", "📊 Трафік: {used} (без обмежень)", "📊 Trafik: {used} (limitsiz)",
                                            "📊 Trafik: {used} (cheklovsiz)", "📊 Трафик: {used} (шектеусіз)", "📊 Trafik: {used} (sınırsız)"),
    "📅 Бессрочно": ("📅 No expiry", "📅 Безстроково", "📅 Müddətsiz", "📅 Muddatsiz", "📅 Мерзімсіз", "📅 Süresiz"),
    "Пробный период уже был выдан этому Telegram-аккаунту.": (
        "A free trial has already been given to this Telegram account.", "Пробний період уже надавався цьому Telegram-акаунту.",
        "Bu Telegram hesabına sınaq müddəti artıq verilib.", "Bu Telegram akkauntiga sinov davri allaqachon berilgan.",
        "Бұл Telegram аккаунтына сынақ мерзімі берілген.", "Bu Telegram hesabına deneme süresi zaten verildi."),
    "📅 Действует до {date}": ("📅 Valid until {date}", "📅 Діє до {date}", "📅 {date} tarixinədək", "📅 {date} gacha amal qiladi",
                               "📅 {date} дейін жарамды", "📅 {date} tarihine kadar geçerli"),
    " (осталось {days} дн.)": (" ({days} days left)", " (залишилось {days} дн.)", " ({days} gün qalıb)", " ({days} kun qoldi)",
                               " ({days} күн қалды)", " ({days} gün kaldı)"),
    "⛔ <b>Ваша подписка на VPN закончилась.</b>\nПродлить: /buy — или напишите в поддержку.": (
        "⛔ <b>Your VPN subscription has ended.</b>\nExtend: /buy — or contact support.",
        "⛔ <b>Ваша підписка на VPN закінчилась.</b>\nПродовжити: /buy — або напишіть у підтримку.",
        "⛔ <b>VPN abunəniz bitib.</b>\nUzatmaq: /buy — və ya dəstəyə yazın.",
        "⛔ <b>VPN obunangiz tugadi.</b>\nUzaytirish: /buy — yoki yordamga yozing.",
        "⛔ <b>VPN жазылымыңыз аяқталды.</b>\nҰзарту: /buy — немесе қолдау қызметіне жазыңыз.",
        "⛔ <b>VPN aboneliğiniz sona erdi.</b>\nUzatmak için: /buy — veya desteğe yazın."),
    "⛔ <b>Трафик закончился</b> ({limit}).\nДоступ приостановлен — продлите подписку (/buy) или напишите в поддержку.": (
        "⛔ <b>Out of traffic</b> ({limit}).\nAccess is paused — extend your subscription (/buy) or contact support.",
        "⛔ <b>Трафік закінчився</b> ({limit}).\nДоступ призупинено — продовжіть підписку (/buy) або напишіть у підтримку.",
        "⛔ <b>Trafik bitib</b> ({limit}).\nGiriş dayandırılıb — abunəni uzadın (/buy) və ya dəstəyə yazın.",
        "⛔ <b>Trafik tugadi</b> ({limit}).\nKirish toʻxtatildi — obunani uzaytiring (/buy) yoki yordamga yozing.",
        "⛔ <b>Трафик бітті</b> ({limit}).\nҚолжетімділік тоқтатылды — жазылымды ұзартыңыз (/buy) немесе қолдау қызметіне жазыңыз.",
        "⛔ <b>Trafik bitti</b> ({limit}).\nErişim durduruldu — aboneliği uzatın (/buy) veya desteğe yazın."),
    "<b>Как подключиться:</b>\n1. Установите приложение: <b>Happ</b> (Android/iPhone) или <b>v2RayTun</b>.\n2. Нажмите «Подключить» ниже — откроется страница под ваше устройство с кнопкой добавления.\n   Или скопируйте ссылку и вставьте в приложении через «+» → «Из буфера».": (
        "<b>How to connect:</b>\n1. Install the app: <b>Happ</b> (Android/iPhone) or <b>v2RayTun</b>.\n2. Tap “Connect” below — a page for your device with an add button will open.\n   Or copy the link and paste it in the app via “+” → “From clipboard”.",
        "<b>Як підключитися:</b>\n1. Встановіть застосунок: <b>Happ</b> (Android/iPhone) або <b>v2RayTun</b>.\n2. Натисніть «Підключити» нижче — відкриється сторінка для вашого пристрою з кнопкою додавання.\n   Або скопіюйте посилання й вставте в застосунку через «+» → «З буфера».",
        "<b>Necə qoşulmaq olar:</b>\n1. Tətbiqi quraşdırın: <b>Happ</b> (Android/iPhone) və ya <b>v2RayTun</b>.\n2. Aşağıda «Qoşul» düyməsinə basın — cihazınız üçün əlavə etmə düyməsi olan səhifə açılacaq.\n   Və ya linki kopyalayıb tətbiqdə «+» → «Buferdən» ilə yapışdırın.",
        "<b>Qanday ulanish:</b>\n1. Ilovani oʻrnating: <b>Happ</b> (Android/iPhone) yoki <b>v2RayTun</b>.\n2. Quyidagi «Ulanish» tugmasini bosing — qurilmangiz uchun qoʻshish tugmasi bor sahifa ochiladi.\n   Yoki havolani nusxalab, ilovada «+» → «Buferdan» orqali joylang.",
        "<b>Қалай қосылу керек:</b>\n1. Қолданбаны орнатыңыз: <b>Happ</b> (Android/iPhone) немесе <b>v2RayTun</b>.\n2. Төмендегі «Қосылу» батырмасын басыңыз — құрылғыңызға арналған қосу батырмасы бар бет ашылады.\n   Немесе сілтемені көшіріп, қолданбада «+» → «Буферден» арқылы қойыңыз.",
        "<b>Nasıl bağlanılır:</b>\n1. Uygulamayı yükleyin: <b>Happ</b> (Android/iPhone) veya <b>v2RayTun</b>.\n2. Aşağıdaki “Bağlan”a dokunun — cihazınıza uygun, ekleme düğmeli bir sayfa açılır.\n   Ya da bağlantıyı kopyalayıp uygulamada “+” → “Panodan” ile yapıştırın."),
    "⏳ <b>Подписка на VPN заканчивается через {days} дн.</b> — {date}.\nПродлите её заранее, чтобы не остаться без доступа. /buy": (
        "⏳ <b>Your VPN subscription ends in {days} days</b> — {date}.\nExtend it in advance so you don't lose access. /buy",
        "⏳ <b>Підписка на VPN закінчується через {days} дн.</b> — {date}.\nПродовжте її заздалегідь, щоб не залишитися без доступу. /buy",
        "⏳ <b>VPN abunəniz {days} gün sonra bitir</b> — {date}.\nGirişsiz qalmamaq üçün əvvəlcədən uzadın. /buy",
        "⏳ <b>VPN obunangiz {days} kundan keyin tugaydi</b> — {date}.\nKirishsiz qolmaslik uchun oldindan uzaytiring. /buy",
        "⏳ <b>VPN жазылымы {days} күннен кейін аяқталады</b> — {date}.\nҚолжетімсіз қалмау үшін алдын ала ұзартыңыз. /buy",
        "⏳ <b>VPN aboneliğiniz {days} gün sonra bitiyor</b> — {date}.\nErişimsiz kalmamak için önceden uzatın. /buy"),
    "⚠️ <b>Израсходовано {pct} трафика</b>: {used} из {limit}.\nОсталось {left}.": (
        "⚠️ <b>{pct} of traffic used</b>: {used} of {limit}.\n{left} left.",
        "⚠️ <b>Використано {pct} трафіку</b>: {used} з {limit}.\nЗалишилось {left}.",
        "⚠️ <b>Trafikin {pct}-i istifadə olunub</b>: {used} / {limit}.\n{left} qalıb.",
        "⚠️ <b>Trafikning {pct} qismi sarflandi</b>: {used} / {limit}.\n{left} qoldi.",
        "⚠️ <b>Трафиктің {pct} жұмсалды</b>: {used} / {limit}.\n{left} қалды.",
        "⚠️ <b>Trafiğin {pct} kadarı kullanıldı</b>: {used} / {limit}.\n{left} kaldı."),
    "✅ Telegram привязан — буду присылать напоминания об оплате и трафике.": (
        "✅ Telegram linked — I'll send reminders about payment and traffic.", "✅ Telegram прив'язано — надсилатиму нагадування про оплату й трафік.",
        "✅ Telegram bağlandı — ödəniş və trafik barədə xatırlatmalar göndərəcəyəm.", "✅ Telegram bogʻlandi — toʻlov va trafik haqida eslatmalar yuboraman.",
        "✅ Telegram байланыстырылды — төлем мен трафик туралы еске салып отырамын.", "✅ Telegram bağlandı — ödeme ve trafik hatırlatmaları göndereceğim."),
    "Ссылка-приглашение недействительна. Попросите администратора новую.": (
        "The invitation link is invalid. Ask the administrator for a new one.", "Посилання-запрошення недійсне. Попросіть в адміністратора нове.",
        "Dəvət linki etibarsızdır. Administratordan yenisini istəyin.", "Taklif havolasi yaroqsiz. Administratordan yangisini soʻrang.",
        "Шақыру сілтемесі жарамсыз. Әкімшіден жаңасын сұраңыз.", "Davet bağlantısı geçersiz. Yöneticiden yenisini isteyin."),
    "👋 Здравствуйте! Это бот nicro VPN.\n\nЕсли у вас уже есть доступ, <b>пришлите сюда свою ссылку-подписку</b> или любой ключ vless://… (в приложении: профиль → поделиться / скопировать) — я узнаю ваш аккаунт.\n\nВаш Telegram ID: <code>{chat_id}</code>\n🌐 /lang — Language": (
        "👋 Hello! This is the nicro VPN bot.\n\nIf you already have access, <b>send your subscription link here</b> or any vless://… key (in the app: profile → share / copy) and I'll recognise your account.\n\nYour Telegram ID: <code>{chat_id}</code>\n🌐 /lang — Language",
        "👋 Вітаю! Це бот nicro VPN.\n\nЯкщо у вас уже є доступ, <b>надішліть сюди своє посилання-підписку</b> або будь-який ключ vless://… (у застосунку: профіль → поділитися / скопіювати) — я впізнаю ваш акаунт.\n\nВаш Telegram ID: <code>{chat_id}</code>\n🌐 /lang — Мова",
        "👋 Salam! Bu nicro VPN botudur.\n\nArtıq girişiniz varsa, <b>abunə linkinizi bura göndərin</b> və ya istənilən vless://… açarını (tətbiqdə: profil → paylaş / kopyala) — hesabınızı tanıyacağam.\n\nTelegram ID-niz: <code>{chat_id}</code>\n🌐 /lang — Dil",
        "👋 Assalomu alaykum! Bu nicro VPN boti.\n\nAgar sizda kirish boʻlsa, <b>obuna havolangizni shu yerga yuboring</b> yoki istalgan vless://… kalitini (ilovada: profil → ulashish / nusxalash) — akkauntingizni taniyman.\n\nTelegram ID: <code>{chat_id}</code>\n🌐 /lang — Til",
        "👋 Сәлеметсіз бе! Бұл nicro VPN боты.\n\nЕгер сізде қолжетімділік болса, <b>жазылым сілтемесін осында жіберіңіз</b> немесе кез келген vless://… кілтін (қолданбада: профиль → бөлісу / көшіру) — аккаунтыңызды танимын.\n\nСіздің Telegram ID: <code>{chat_id}</code>\n🌐 /lang — Тіл",
        "👋 Merhaba! Burası nicro VPN botu.\n\nZaten erişiminiz varsa <b>abonelik bağlantınızı buraya gönderin</b> ya da herhangi bir vless://… anahtarını (uygulamada: profil → paylaş / kopyala) — hesabınızı tanırım.\n\nTelegram ID'niz: <code>{chat_id}</code>\n🌐 /lang — Dil"),
    "✉️ Передал в поддержку — ответ придёт сюда.": (
        "✉️ Passed to support — the answer will come here.", "✉️ Передав у підтримку — відповідь прийде сюди.", "✉️ Dəstəyə ötürdüm — cavab bura gələcək.",
        "✉️ Yordamga yubordim — javob shu yerga keladi.", "✉️ Қолдау қызметіне жібердім — жауап осында келеді.", "✉️ Desteğe ilettim — yanıt buraya gelecek."),
    "Ошибка": ("Error", "Помилка", "Xəta", "Xato", "Қате", "Hata"),
    "Создаю счёт…": ("Creating an invoice…", "Створюю рахунок…", "Hesab yaradılır…", "Hisob yaratilmoqda…", "Шот жасалуда…", "Fatura oluşturuluyor…"),
    "Спасибо! Администратор проверит перевод и продлит доступ.": (
        "Thank you! The administrator will check the transfer and extend your access.", "Дякуємо! Адміністратор перевірить переказ і продовжить доступ.",
        "Təşəkkürlər! Administrator köçürməni yoxlayıb girişi uzadacaq.", "Rahmat! Administrator oʻtkazmani tekshirib, kirishni uzaytiradi.",
        "Рахмет! Әкімші аударымды тексеріп, қолжетімділікті ұзартады.", "Teşekkürler! Yönetici havaleyi kontrol edip erişimi uzatacak."),
    "Android": ("Android",) * 6,
    "iPhone / iPad": ("iPhone / iPad",) * 6,
    "Windows": ("Windows",) * 6,
    "Mac": ("Mac",) * 6,
    "Linux": ("Linux",) * 6,
    "ваше устройство": ("your device", "вашому пристрої", "cihazınız", "qurilmangiz", "құрылғыңыз", "cihazınız"),
    "🇳🇱 Основной сервер": ("🇳🇱 Main server", "🇳🇱 Основний сервер", "🇳🇱 Əsas server", "🇳🇱 Asosiy server", "🇳🇱 Негізгі сервер", "🇳🇱 Ana sunucu"),
    "nicro — состояние серверов": ("nicro — server status", "nicro — стан серверів", "nicro — serverlərin vəziyyəti", "nicro — serverlar holati",
                                   "nicro — серверлер күйі", "nicro — sunucu durumu"),
    "ЮKassa — карты, СБП, кошельки": ("YooKassa — cards, SBP, wallets", "ЮKassa — картки, СБП, гаманці", "YooKassa — kartlar, SBP, pul kisələri",
                                      "YooKassa — kartalar, SBP, hamyonlar", "ЮKassa — карталар, СБП, әмияндар", "YooKassa — kartlar, SBP, cüzdanlar"),
    "CryptoBot — USDT, TON, BTC и др.": ("CryptoBot — USDT, TON, BTC, etc.", "CryptoBot — USDT, TON, BTC тощо", "CryptoBot — USDT, TON, BTC və s.",
                                         "CryptoBot — USDT, TON, BTC va b.", "CryptoBot — USDT, TON, BTC т.б.", "CryptoBot — USDT, TON, BTC vb."),
    "NOWPayments — 200+ криптовалют": ("NOWPayments — 200+ cryptocurrencies", "NOWPayments — 200+ криптовалют", "NOWPayments — 200+ kriptovalyuta",
                                       "NOWPayments — 200+ kriptovalyuta", "NOWPayments — 200+ криптовалюта", "NOWPayments — 200+ kripto para"),
    "Telegram Stars — оплата звёздами в боте": ("Telegram Stars — pay with stars in the bot", "Telegram Stars — оплата зірками в боті",
                                                "Telegram Stars — botda ulduzlarla ödəniş", "Telegram Stars — botda yulduzlar bilan toʻlov",
                                                "Telegram Stars — ботта жұлдызбен төлеу", "Telegram Stars — botta yıldızla ödeme"),
    "Перевод по реквизитам (подтверждает администратор)": (
        "Bank transfer (confirmed by the administrator)", "Переказ за реквізитами (підтверджує адміністратор)",
        "Rekvizitlərlə köçürmə (administrator təsdiqləyir)", "Rekvizitlar boʻyicha oʻtkazma (administrator tasdiqlaydi)",
        "Деректемелер бойынша аударым (әкімші растайды)", "Banka havalesi (yönetici onaylar)"),
    "Промокод не найден": ("Promo code not found", "Промокод не знайдено", "Promokod tapılmadı", "Promokod topilmadi", "Промокод табылмады", "Promosyon kodu bulunamadı"),
    "Срок действия промокода истёк": ("The promo code has expired", "Термін дії промокоду минув", "Promokodun müddəti bitib", "Promokod muddati tugagan",
                                      "Промокодтың мерзімі өтті", "Promosyon kodunun süresi doldu"),
    "Промокод больше не действует": ("The promo code is no longer valid", "Промокод більше не діє", "Promokod artıq keçərli deyil",
                                     "Promokod endi amal qilmaydi", "Промокод енді жарамсыз", "Promosyon kodu artık geçerli değil"),
    "Вы уже использовали этот промокод": ("You have already used this promo code", "Ви вже використали цей промокод", "Bu promokoddan artıq istifadə etmisiniz",
                                          "Siz bu promokoddan allaqachon foydalangansiz", "Сіз бұл промокодты қолданып қойдыңыз", "Bu promosyon kodunu zaten kullandınız"),
    "Промокоды сейчас не принимаются": ("Promo codes aren't accepted right now", "Промокоди зараз не приймаються", "Promokodlar hazırda qəbul edilmir",
                                        "Promokodlar hozir qabul qilinmaydi", "Промокодтар қазір қабылданбайды", "Promosyon kodları şu anda kabul edilmiyor"),
    "Этот способ оплаты не подключён": ("This payment method isn't connected", "Цей спосіб оплати не підключено", "Bu ödəniş üsulu qoşulmayıb",
                                        "Bu toʻlov usuli ulanmagan", "Бұл төлем тәсілі қосылмаған", "Bu ödeme yöntemi bağlı değil"),
    "Тариф недоступен для оплаты": ("This plan can't be paid for", "Тариф недоступний для оплати", "Tarif ödəniş üçün əlçatan deyil",
                                    "Tarifni toʻlab boʻlmaydi", "Тарифті төлеу мүмкін емес", "Bu tarife için ödeme yapılamaz"),
    "Слишком много неоплаченных счетов — оплатите созданный или подождите час": (
        "Too many unpaid invoices — pay the existing one or wait an hour", "Забагато неоплачених рахунків — оплатіть створений або зачекайте годину",
        "Çoxlu ödənilməmiş hesab var — yaradılanı ödəyin və ya bir saat gözləyin", "Toʻlanmagan hisoblar juda koʻp — yaratilganini toʻlang yoki bir soat kuting",
        "Төленбеген шоттар тым көп — жасалғанын төлеңіз немесе бір сағат күтіңіз", "Çok fazla ödenmemiş fatura var — mevcut olanı ödeyin veya bir saat bekleyin"),
}


def used_keys() -> set[str]:
    """Texts passed to t(lang, "...") in the code (plus dict values inside t(lang, {...}[x]))."""
    keys = set()
    for f in APP.rglob("*.py"):
        for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "t" and len(n.args) >= 2:
                a = n.args[1]
                if isinstance(a, ast.Constant) and isinstance(a.value, str):
                    keys.add(a.value)
                elif isinstance(a, ast.Subscript) and isinstance(a.value, ast.Dict):
                    keys.update(v.value for v in a.value.values)
    return keys


def main():
    missing = used_keys() - set(T)
    if missing:
        raise SystemExit("no translation for:\n" + "\n".join(sorted(missing)))
    for k, v in T.items():
        want = sorted(re.findall(r"\{\w+\}", k))
        for lang, tr in zip(ALL, v):
            assert sorted(re.findall(r"\{\w+\}", tr)) == want, (lang, k, tr)
    out = APP / "locales"
    out.mkdir(exist_ok=True)
    for lang in LANGS:
        i = ALL.index(lang)
        (out / f"{lang}.json").write_text(json.dumps({k: v[i] for k, v in T.items()}, ensure_ascii=False, indent=1),
                                          encoding="utf-8")
    print(f"{len(T)} texts x {len(LANGS)} languages written to {out}")


if __name__ == "__main__":
    main()
