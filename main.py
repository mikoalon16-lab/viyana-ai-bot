import logging
import os
import random
import sqlite3
import time
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatPermissions
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
)
from openai import OpenAI

# =========================================================
# CONFIG & ENVIRONMENT VARIABLES
# =========================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# OpenAI Client (çeviri için)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

# =========================================================
# DATABASE (SQLITE)
# =========================================================

def init_db():
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            chat_id INTEGER,
            xp INTEGER DEFAULT 0,
            level INTEGER DEFAULT 1,
            coins INTEGER DEFAULT 100,
            title TEXT DEFAULT 'Yeni Üye / Новичок',
            last_daily INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()

def add_xp_and_coins(user_id, chat_id, xp_amount=10, coin_amount=5):
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT xp, level, coins FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    
    if row is None:
        cursor.execute(
            "INSERT INTO users (user_id, chat_id, xp, level, coins) VALUES (?, ?, ?, ?, ?)",
            (user_id, chat_id, xp_amount, 1, 100 + coin_amount)
        )
    else:
        new_xp = row[0] + xp_amount
        new_level = int(new_xp / 100) + 1
        new_coins = row[2] + coin_amount
        
        cursor.execute(
            "UPDATE users SET xp = ?, level = ?, coins = ? WHERE user_id = ?",
            (new_xp, new_level, new_coins, user_id)
        )
    conn.commit()
    conn.close()

# =========================================================
# KELİME HAVUZU
# =========================================================

KELIME_HAVUZU = [
    {"kelime": "VIYANA", "ipucu": "Avusturya'nın başkenti ve botumuzun ismi"},
    {"kelime": "TELEGRAM", "ipucu": "Mavi simgeli, kanalları olan popüler mesajlaşma uygulaması"},
    {"kelime": "YAZILIM", "ipucu": "Bilgisayar sistemlerini çalıştırmaya yarayan kodlar bütünü"},
    {"kelime": "BAKLAVA", "ipucu": "Gaziantep ile özdeşleşmiş şerbetli tatlı"},
    {"kelime": "SATRANÇ", "ipucu": "64 karelik tahtada şahı mat etmeye çalışan strateji oyunu"},
    {"kelime": "KAPADOKYA", "ipucu": "Peri bacaları ve sıcak hava balonlarıyla ünlü bölgemiz"},
    {"kelime": "İSTANBUL", "ipucu": "İki kıtayı birbirine bağlayan tarihi metropolümüz"},
    {"kelime": "KÜTÜPHANE", "ipucu": "Binlerce kitabın sessizlik içinde okunduğu yer"},
    {"kelime": "GÖKYÜZÜ", "ipucu": "Gündüzleri mavi, geceleri yıldızlarla kaplı tavan"},
    {"kelime": "KAHVE", "ipucu": "Kırk yıl hatırı olan, sabahsız içilmeyen sıcak içecek"},
    {"kelime": "ÇİKOLATA", "ipucu": "Kakao yağından yapılan, mutluluk hormonu salgılatan tatlı"},
    {"kelime": "ŞELALE", "ipucu": "Yüksekten coşkuyla dökülen akarsu, çağlayan"},
    {"kelime": "LİMONATA", "ipucu": "Yaz aylarında ferahlatıcı, ekşi-tatlı soğuk içecek"},
    {"kelime": "OKYANUS", "ipucu": "Kıtaları birbirinden ayıran devasa tuzlu su kütlesi"},
    {"kelime": "KUMANDAN", "ipucu": "Orduyu sevk ve idare eden yüksek rütbeli asker"},
    {"kelime": "FOTOĞRAF", "ipucu": "Anıları ölümsüzleştiren ışık baskısı resmi"},
    {"kelime": "ASTRONOT", "ipucu": "Uzay aracıyla uzaya giden araştırmacı bilim insanı"},
    {"kelime": "MÜZİSYEN", "ipucu": "Enstrüman çalan veya beste yapan sanatçı"},
    {"kelime": "GÜNEŞLİK", "ipucu": "Pencereden giren fazla ışığı kesen perde"},
    {"kelime": "PUSULA", "ipucu": "Magnetik ibresiyle daima kuzeyi gösteren yön bulucu"},
    {"kelime": "MİKROSKOP", "ipucu": "Gözle görülmeyen hücreleri binlerce kat büyüten cihaz"},
    {"kelime": "TELESKOP", "ipucu": "Gezegenleri ve yıldızları yakınlaştırıp inceleyen tüp"},
    {"kelime": "TİYATRO", "ipucu": "Sahnede canlı olarak sergilenen oyun sanatı"},
    {"kelime": "ANITKABİR", "ipucu": "Atatürk'ün Ankara'daki ebedi istirahatgahı"},
    {"kelime": "PRAMİT", "ipucu": "Mısır'da bulunan üçgen yüzeyli devasa tarihi yapılar"},
    {"kelime": "ZAMAN", "ipucu": "Akıp giden, geri döndürülemeyen kavram"},
    {"kelime": "MUCİZE", "ipucu": "İnsanları hayrete düşüren olağanüstü olay"},
    {"kelime": "FIRTINA", "ipucu": "Güçlü rüzgarlarla gelen şiddetli hava olayı"},
    {"kelime": "MİMARLIK", "ipucu": "Binaları ve yapıları tasarlama sanatı"},
    {"kelime": "ORMAN", "ipucu": "Ağaçlarla kaplı doğal yaşam alanı"},
    {"kelime": "KELEBEK", "ipucu": "Rengarenk kanatlı narin böcek"},
    {"kelime": "KARTAL", "ipucu": "Yükseklerde uçan keskin gözlü yırtıcı kuş"},
    {"kelime": "DENİZKIZI", "ipucu": "Efsanevi yarısı kadın yarısı balık yaratık"},
    {"kelime": "VOLKAN", "ipucu": "Lava ve kül püskürten dağ"},
    {"kelime": "LABİRENT", "ipucu": "Çıkışı bulunması zor karmakarışık yollar"},
    {"kelime": "ORCHESTRA", "ipucu": "Çok sayıda müzisyenin oluşturduğu grup"},
    {"kelime": "GÜMÜŞ", "ipucu": "Değerli bir maden ve renk"},
    {"kelime": "ŞAMPİYON", "ipucu": "Yarışmayı birincilikle bitiren kişi veya takım"},
    {"kelime": "MEYDAN", "ipucu": "Şehirlerin merkezindeki geniş açık alan"},
    {"kelime": "TİMSAH", "ipucu": "Suda ve karada yaşayan keskin dişli sürüngen"},
    {"kelime": "GÜVERCİN", "ipucu": "Barışın simgesi olan kuş"},
    {"kelime": "PENGUEN", "ipucu": "Kutup bölgesinde yaşayan uçamayan sevimli kuş"},
    {"kelime": "ZÜRAFA", "ipucu": "Uzun boynuyla bilinen kara hayvanı"},
    {"kelime": "KANGURU", "ipucu": "Yavrularını kesesinde taşıyan Avustralya hayvanı"},
    {"kelime": "MAMUT", "ipucu": "Soyu tükenmiş tüylü dev fil"},
    {"kelime": "DİNOZOR", "ipucu": "Milyonlarca yıl önce yaşamış dev sürüngen"},
    {"kelime": "GALAKSİ", "ipucu": "Milyarlarca yıldızdan oluşan dev sistem"},
    {"kelime": "GEZEGEN", "ipucu": "Güneş etrafında dolanan gök cismi"},
    {"kelime": "YILDIZ", "ipucu": "Gece gökyüzünde parlayan sıcak gaz kütlesi"},
    {"kelime": "METEOR", "ipucu": "Atmosphere girince yanan gök taşı"},
    {"kelime": "SÜPERNOVA", "ipucu": "Büyük bir yıldızın patlaması"},
    {"kelime": "YERÇEKİMİ", "ipucu": "Cisimleri dünyanın merkezine çeken kuvvet"},
    {"kelime": "OKSİJEN", "ipucu": "Nefes almamızı sağlayan yaşamsal gaz"},
    {"kelime": "ATMOSFER", "ipucu": "Dünyayı saran gaz tabakası"},
    {"kelime": "FOTOSENTEZ", "ipucu": "Bitkilerin ışıkla besin üretmesi"},
    {"kelime": "DNA", "ipucu": "Genetik kodlarımızı taşıyan molekül"},
    {"kelime": "PROTEİN", "ipucu": "Kas gelişimi için gerekli besin öğesi"},
    {"kelime": "VITAMIN", "ipucu": "Vücut direnci için gerekli organik bileşik"},
    {"kelime": "KALP", "ipucu": "Vücuda kan pompalayan hayati organ"},
    {"kelime": "BEYİN", "ipucu": "Düşünme ve yönetim merkezimiz"},
    {"kelime": "AKCİĞER", "ipucu": "Solunum yapmamızı sağlayan organ"},
    {"kelime": "İSKELET", "ipucu": "Vücudumuza şekil veren kemik çatısı"},
    {"kelime": "DAMAR", "ipucu": "Kanın vücutta dolaştığı boru sistemi"},
    {"kelime": "SİNİR", "ipucu": "Sinyalleri beyne ileten iletken ağ"},
    {"kelime": "KAS", "ipucu": "Hareket etmemizi sağlayan lifli doku"},
    {"kelime": "AMELİYAT", "ipucu": "Cerrahi müdahale operasyonu"},
    {"kelime": "MÜZECİLİK", "ipucu": "Tarihi eserleri koruma ve sergileme işi"},
    {"kelime": "ARKEOLOJİ", "ipucu": "Kazı bilimi"},
    {"kelime": "MİTOLOJİ", "ipucu": "Eski efsaneler ve tanrılar bilimi"},
    {"kelime": "FELSEFE", "ipucu": "Düşünce ve bilgelik arayışı"},
    {"kelime": "PSİKOLOJİ", "ipucu": "İnsan davranışı ve zihin bilimi"},
    {"kelime": "SOSYOLOJİ", "ipucu": "Toplum bilimi"},
    {"kelime": "EKONOMİ", "ipucu": "Üretim, tüketim ve para yönetimi"},
    {"kelime": "POLİTİKA", "ipucu": "Devlet yönetimi sanatı"},
    {"kelime": "HUKUK", "ipucu": "Adalet ve yasalar bütünü"},
    {"kelime": "ANAYASA", "ipucu": "Bir devletin temel kanunu"},
    {"kelime": "MAHKEME", "ipucu": "Adaletin dağıtıldığı resmi kurum"},
    {"kelime": "AVUKAT", "ipucu": "Hak savunan hukukçu"},
    {"kelime": "HÂKİM", "ipucu": "Karar veren yargıç"},
    {"kelime": "SAVCI", "ipucu": "Devlet adına suçlamayı yapan hukukçu"},
    {"kelime": "HAPİSHANE", "ipucu": "Cezaların çekildiği yer"},
    {"kelime": "ÖZGÜRLÜK", "ipucu": "Kendi iradesiyle hareket edebilme durumu"},
    {"kelime": "EŞİTLİK", "ipucu": "Herkesin aynı haklara sahip olması"},
    {"kelime": "DEMOKRASİ", "ipucu": "Halkın kendi kendini yönetmesi"},
    {"kelime": "CUMHURİYET", "ipucu": "Halk egemenliğine dayanan devlet şekli"},
    {"kelime": "BAYRAK", "ipucu": "Bir ulusun bağımsızlık simgesi"},
    {"kelime": "İSTİKLAL", "ipucu": "Bağımsızlık, özgürce yaşama"},
    {"kelime": "VATAN", "ipucu": "Üzerinde yaşanılan toprak parçası"},
    {"kelime": "MİLLET", "ipucu": "Aynı toprakta yaşayan insan topluluğu"},
    {"kelime": "TÜRKLÜK", "ipucu": "Türk olma durumu ve kimliği"},
    {"kelime": "SAVAŞ", "ipucu": "Silahlı mücadele durumu"},
    {"kelime": "BARIŞ", "ipucu": "Çatışmasızlık ve huzur hali"},
    {"kelime": "ZAFER", "ipucu": "Savaşta veya yarışta kazanılan başarı"},
    {"kelime": "ORDU", "ipucu": "Ülkeyi koruyan silahlı kuvvetler"},
    {"kelime": "ASKER", "ipucu": "Vatan savunması yapan kişi"},
    {"kelime": "ŞEHİT", "ipucu": "Kutsal değerler uğruna can veren kişi"},
    {"kelime": "GAZİ", "ipucu": "Savaştan sağ ve zaferle dönen asker"},
    {"kelime": "KALE", "ipucu": "Savunma amaçlı surlu büyük yapı"},
    {"kelime": "SARAY", "ipucu": "Hükümdarların yaşadığı gösterişli bina"},
    {"kelime": "SUR", "ipucu": "Şehirleri koruyan yüksek taş duvarlar"},
    {"kelime": "KILIÇ", "ipucu": "Eski zaman kesici silahı"},
    {"kelime": "KALKAN", "ipucu": "Ok ve kılıç darbelerinden koruyan siper"},
    {"kelime": "OKÇULUK", "ipucu": "Yay ile ok atma sanatı ve sporu"},
    {"kelime": "MIZRAK", "ipucu": "Ucu sivri uzun savunma silahı"},
    {"kelime": "ZIRH", "ipucu": "Vücudu koruyan metal giysi"},
    {"kelime": "KAZAN", "ipucu": "Büyük yemek pişirme kabı"},
    {"kelime": "MEŞALE", "ipucu": "Aydınlatma sağlayan ucu yanıcı değnek"},
    {"kelime": "KANDİL", "ipucu": "İçinde yağ yanan eski aydınlatma aracı"},
    {"kelime": "MUM", "ipucu": "Eritilerek ışık veren fitilli nesne"},
    {"kelime": "AMBULANS", "ipucu": "Hasta taşıyan acil müdahale aracı"},
    {"kelime": "İTFAİYE", "ipucu": "Yangın söndüren ekip ve araç"},
    {"kelime": "POLİS", "ipucu": "Kamu düzenini sağlayan güvenlik görevlisi"},
    {"kelime": "DOKTOR", "ipucu": "Hastaları tedavi eden tıp uzmanı"},
    {"kelime": "HEMŞİRE", "ipucu": "Hastalara bakım sağlayan sağlık çalışanı"},
    {"kelime": "ECZANE", "ipucu": "İlaçların satıldığı yer"},
    {"kelime": "HASTANE", "ipucu": "Tedavi olunan sağlık kurumu"},
    {"kelime": "ŞİFA", "ipucu": "Hastalıktan kurtulup sağlığına kavuşma"},
    {"kelime": "İLAÇ", "ipucu": "Hastalığı iyileştiren kimyasal veya doğal madde"},
    {"kelime": "AŞI", "ipucu": "Hastalıkları önleyen koruyucu sıvı"},
    {"kelime": "SALGIN", "ipucu": "Hızla yayılan hastalık durumu"},
    {"kelime": "KARANTİNA", "ipucu": "Bulaşıcı hastalıktan korunma tecridi"},
    {"kelime": "MASKE", "ipucu": "Yüzü ve solunumu koruyan siperlik"},
    {"kelime": "TEMİZLİK", "ipucu": "Hijyenik ve kirden arınmış olma hali"},
    {"kelime": "SABUN", "ipucu": "Köpürerek kirleri çözen temizlik maddesi"},
    {"kelime": "KOLONYA", "ipucu": "Alkollü güzel kokulu ferahlatıcı sıvı"},
    {"kelime": "PARFÜM", "ipucu": "Güzel koku yayan esans"},
    {"kelime": "AYNA", "ipucu": "Görüntüyü birebir yansıtan cam"},
    {"kelime": "TARAK", "ipucu": "Saçları düzeltmeye yarayan dişli araç"},
    {"kelime": "MAKAS", "ipucu": "Kağıt ve kumaş kesen iki bıçaklı alet"},
    {"kelime": "İĞNE", "ipucu": "Dikiş dikmeye yarayan ucu sivri metal"},
    {"kelime": "İPLİK", "ipucu": "Dikişte kullanılan ince dokuma lifi"},
    {"kelime": "DÜĞME", "ipucu": "Giysileri iliklemeye yarayan küçük nesne"},
    {"kelime": "FERMUAR", "ipucu": "Giysileri kapatan dişli şerit"},
    {"kelime": "KUMAŞ", "ipucu": "İplikten dokunan giysi malzemesi"},
    {"kelime": "TERZİ", "ipucu": "Kıyafet diken ve tamir eden usta"},
    {"kelime": "AYAKKABI", "ipucu": "Ayağa giyilen koruyucu giysi"},
    {"kelime": "ÇORAP", "ipucu": "Ayağa giyilen örme giysi"},
    {"kelime": "ŞAPKACILIK", "ipucu": "Başlık tasarlama ve üretme sanatı"},
    {"kelime": "GÖZLÜK", "ipucu": "Görmeyi kolaylaştıran lensli araç"},
    {"kelime": "SAAT", "ipucu": "Zamanı gösteren kadranlı cihaz"},
    {"kelime": "YÜZÜK", "ipucu": "Parmağa takılan takı"},
    {"kelime": "KOLYECİLİK", "ipucu": "Boyna takılan süs eşyası yapımı"},
    {"kelime": "BİLEZİK", "ipucu": "Bileğe takılan değerli takı"},
    {"kelime": "ALTIN", "ipucu": "Sarı renkli çok Değerli maden"},
    {"kelime": "ELMAS", "ipucu": "Doğadaki en sert kıymetli taş"},
    {"kelime": "ZÜMRÜT", "ipucu": "Yeşil renkli değerli taş"},
    {"kelime": "YAKUT", "ipucu": "Kırmızı renkli değerli taş"},
    {"kelime": "SAFİR", "ipucu": "Mavi renkli değerli taş"},
    {"kelime": "INCI", "ipucu": "Istiridye içinden çıkan parlak süs nesnesi"},
    {"kelime": "HAZİNE", "ipucu": "Gömülü veya saklı değerli eşyalar"},
    {"kelime": "DEFİNE", "ipucu": "Toprak altına saklanmış servet"},
    {"kelime": "MÜCEVHER", "ipucu": "Değerli taşlarla yapılan süs eşyaları"},
    {"kelime": "BANKA", "ipucu": "Para ve finans işlemlerinin yapıldığı kurum"},
    {"kelime": "KREDİ", "ipucu": "Bankadan alınan geri ödemeli borç"},
    {"kelime": "FAİZ", "ipucu": "Paranın kullanım bedeli oransal getirisi"},
    {"kelime": "BORÇ", "ipucu": "Geri ödenmesi gereken para veya yükümlülük"},
    {"kelime": "SERVET", "ipucu": "Büyük mal ve para varlığı"},
    {"kelime": "SERMAYE", "ipucu": "İş kurmak için gereken anapara"},
    {"kelime": "YATIRIM", "ipucu": "Kazanç sağlamak amacıyla yapılan harcama"},
    {"kelime": "TİCARET", "ipucu": "Mal alım satım işi"},
    {"kelime": "PAZAR", "ipucu": "Ürünlerin satıldığı açık alışveriş alanı"},
    {"kelime": "MARKET", "ipucu": "Çeşitli ihtiyaç maddelerinin satıldığı mağaza"},
    {"kelime": "ALIŞVERİŞ", "ipucu": "Para karşılığı mal edinme süreci"},
    {"kelime": "Fatura", "ipucu": "Ödenmesi gereken hizmet belgesi"},
    {"kelime": "MAKBUZ", "ipucu": "Ödemenin yapıldığını gösteren belge"},
    {"kelime": "SÖZLEŞME", "ipucu": "İki taraf arasındaki resmi anlaşma"},
    {"kelime": "İMZA", "ipucu": "Kişinin adını onay için kendi eliyle yazması"},
    {"kelime": "MÜHÜR", "ipucu": "Resmi belgeleri onaylayan damga"},
    {"kelime": "MEKTUP", "ipucu": "Zarf içinde gönderilen yazılı haber"},
    {"kelime": "POSTACILIK", "ipucu": "Posta ve kargo dağıtım işi"},
    {"kelime": "TELGRAF", "ipucu": "Eski zaman elektrikli mesajlaşma aracı"},
    {"kelime": "RADYO", "ipucu": "Ses dalgalarını yayınlayan cihaz"},
    {"kelime": "GAZETE", "ipucu": "Günlük haberlerin basıldığı kağıtyayın"},
    {"kelime": "DERGİ", "ipucu": "Süreli basılan makale ve görsel yayını"},
    {"kelime": "MATBAA", "ipucu": "Baskı ve kitap basım evi"},
    {"kelime": "KÂĞIT", "ipucu": "Üzerine yazı yazılan selüloz yaprak"},
    {"kelime": "KALEM", "ipucu": "Yazı yazma aracı"},
    {"kelime": "SILGI", "ipucu": "Kurşun kalem yazısını silen araç"},
    {"kelime": "DEFTER", "ipucu": "Not almak için ciltlenmiş kağıtlar"},
    {"kelime": "MÜREKKEP", "ipucu": "Yazı yazmaya yarayan renkli sıvı"},
    {"kelime": "SÖZLÜK", "ipucu": "Kelimelerin anlamlarını içeren kitap"},
    {"kelime": "ANSİKLOPEDİ", "ipucu": "Tüm bilgileri kapsayan dev kitap serisi"},
    {"kelime": "ALFABE", "ipucu": "Bir dilin harf dizilimi sırası"},
    {"kelime": "HECE", "ipucu": "Bir solukta çıkan ses topluluğu"},
    {"kelime": "CÜMLE", "ipucu": "Düşünceyi anlatan kelimeler dizisi"},
    {"kelime": "PARAGRAF", "ipucu": "Aynı fikri işleyen cümleler grubu"},
    {"kelime": "ŞİİR", "ipucu": "Duygusal ve ölçülü edebi yazı"},
    {"kelime": "ŞAİR", "ipucu": "Şiir yazan edebi sanatçı"},
    {"kelime": "ROMAN", "ipucu": "Uzun edebi kurgu kitap"},
    {"kelime": "YAZAR", "ipucu": "Kitap ve eser kaleme alan kişi"},
    {"kelime": "HİKÂYE", "ipucu": "Kısa kurgusal anlatı"},
    {"kelime": "MASAL", "ipucu": "Olağanüstü unsurlar içeren çocuk anlatısı"},
    {"kelime": "EFSANE", "ipucu": "Halk arasında anlatılagelen eski öykü"},
    {"kelime": "DESTAN", "ipucu": "Kahramanlıkları anlatan uzun edebi eser"},
    {"kelime": "MİT", "ipucu": "Geleneksel efsanevi inanç öyküsü"},
    {"kelime": "SANAT", "ipucu": "Yaratıcılık ve duygu dışavurumu"},
    {"kelime": "RESSAM", "ipucu": "Tablo ve resim çizen sanatçı"},
    {"kelime": "HEYKEL", "ipucu": "Taş veya kilden yapılan üç boyutlu eser"},
    {"kelime": "MÜZİK", "ipucu": "Seslerin ritmik ve harmonik düzeni"},
    {"kelime": "BESTE", "ipucu": "Müzik eseri yapıtı"},
    {"kelime": "NOTASI", "ipucu": "Müziğin alfabesi ve okuma simgeleri"},
    {"kelime": "GİTAR", "ipucu": "Tellik popüler enstrüman"},
    {"kelime": "PIYANO", "ipucu": "Siyah beyaz tuşları olan vurmalı çalgı"},
    {"kelime": "KEMAN", "ipucu": "Arşe ile çalınan telli zarif enstrüman"},
    {"kelime": "FLÖT", "ipucu": "Üflenerek çalınan delikli çalgı"},
    {"kelime": "DAVUL", "ipucu": "Tokmak ve çubukla çalınan büyük vurmalı çalgı"},
    {"kelime": "BAĞLAMA", "ipucu": "Milli telli çalgımız, saz"},
    {"kelime": "TAMPON", "ipucu": "Kan durdurucu bez veya araç darbe emici"},
    {"kelime": "STADYUM", "ipucu": "Büyük spor müsabakalarının yapıldığı alan"},
    {"kelime": "FUTBOL", "ipucu": "11'er kişilik takımlarla oynanan meşin yuvarlak oyunu"},
    {"kelime": "BASKETBOL", "ipucu": "Potalara top atılarak oynanan salon sporu"},
    {"kelime": "VOLEYBOL", "ipucu": "File üzerinden elle top geçirme sporu"},
    {"kelime": "HENTBOL", "ipucu": "Elle oynanan ve kale olan takım sporu"},
    {"kelime": "TENİS", "ipucu": "Raketle küçük sarı topa vurma sporu"},
    {"kelime": "YÜZME", "ipucu": "Suda kulaç atarak ilerleme sporu"},
    {"kelime": "GÜREŞ", "ipucu": "Ata sporumuz, minder ve er meydanı mücadelesi"},
    {"kelime": "BOKS", "ipucu": "Eldivenlerle ringde yapılan dövüş sporu"},
    {"kelime": "JUDO", "ipucu": "Japon menşeili savunma sporu"},
    {"kelime": "ATLETİZM", "ipucu": "Koşu, atma ve atlama sporlarının genel adı"},
    {"kelime": "KADIN", "ipucu": "Yetişkin dişi insan"},
    {"kelime": "ERKEK", "ipucu": "Yetişkin erkek insan"},
    {"kelime": "ÇOCUK", "ipucu": "Küçük yaştaki insan"},
    {"kelime": "BEBEK", "ipucu": "Yeni doğmuş insan"},
    {"kelime": "ANNE", "ipucu": "Ailenin temeli dişi ebeveyn"},
    {"kelime": "BABA", "ipucu": "Ailenin temeli erkek ebeveyn"},
    {"kelime": "KARDEŞ", "ipucu": "Aynı anne babadan olan çocuklar"},
    {"kelime": "DEDE", "ipucu": "Ebeveynlerin babası"},
    {"kelime": "NİNE", "ipucu": "Ebeveynlerin annesi"},
    {"kelime": "AMCA", "ipucu": "Babanın erkek kardeşi"},
    {"kelime": "HALA", "ipucu": "Babanın kız kardeşi"},
    {"kelime": "DAYI", "ipucu": "Annenin erkek kardeşi"},
    {"kelime": "TEYZE", "ipucu": "Annenin kız kardeşi"},
    {"kelime": "YEĞEN", "ipucu": "Kardeşin çocuğu"},
    {"kelime": "KUZEN", "ipucu": "Teyze, hala, amca veya dayının çocuğu"},
    {"kelime": "AİLE", "ipucu": "Toplumun en küçük birimi ve yuva"},
    {"kelime": "DOST", "ipucu": "İyi ve kötü günde yanında olan arkadaş"},
    {"kelime": "KOMŞU", "ipucu": "Aynı binada veya yakın evde yaşayan kişi"},
    {"kelime": "MİSAFİR", "ipucu": "Eve konuk olarak gelen kişi"},
    {"kelime": "AŞÇI", "ipucu": "Yemekleri profesyonelce pişiren usta"},
    {"kelime": "GARSON", "ipucu": "Restoranda servis yapan çalışan"},
    {"kelime": "MÜHENDİS", "ipucu": "Teknik ve tasarım uzmanı"},
    {"kelime": "MİMAR", "ipucu": "Bina çizen ve tasarlayan uzman"},
    {"kelime": "ÖĞRETMEN", "ipucu": "Okulda öğrencilere bilgi öğreten kişi"},
    {"kelime": "ÖĞRENCİ", "ipucu": "Ders alıp eğitim gören kişi"},
    {"kelime": "MÜDÜR", "ipucu": "Okul veya iş yerinin yöneticisi"},
    {"kelime": "ŞÖFÖR", "ipucu": "Arat ve otobüs kullanan sürücü"},
    {"kelime": "PİLOT", "ipucu": "Uçak ve helikopter kullanan kişi"},
    {"kelime": "KAPTAN", "ipucu": "Gemi yönlendiren ve sevk eden kişi"},
    {"kelime": "MADENCİ", "ipucu": "Yerin altından kömür ve maden çıkaran işçi"},
    {"kelime": "ÇİFTÇİ", "ipucu": "Toprağı eken ve tarım yapan kişi"},
    {"kelime": "BALIKÇI", "ipucu": "Denizden balık tutan kişi"},
    {"kelime": "BERBER", "ipucu": "Erkek saç ve sakal kesimi yapan esnaf"},
    {"kelime": "KUAFÖR", "ipucu": "Saç tasarımı ve bakımı yapan salon uzmanı"},
    {"kelime": "MANGAL", "ipucu": "Üzerinde ızgara yapılan közlü ateş kabı"},
    {"kelime": "SEMAVER", "ipucu": "Çayı sürekli sıcak tutan geleneksel demlik ünitesi"},
    {"kelime": "ŞAŞLIK", "ipucu": "Şişe dizilerek pişirilen et yemeği"},
    {"kelime": "PİLAF", "ipucu": "Pirinç veya bulgurdan yapılan lezzetli yemek"},
    {"kelime": "ÇORBA", "ipucu": "Yemeğin başında içilen sıcak sulu başlangıç"},
    {"kelime": "SALATA", "ipucu": "Sebzelerle yapılan zeytinyağlı karışım"},
    {"kelime": "DÖNER", "ipucu": "Dikey şişte dönerek pişen milli et yemeğimiz"},
    {"kelime": "LAHMACUN", "ipucu": "Kıymalı çıtır ince hamur"},
    {"kelime": "PİDE", "ipucu": "Karadeniz ve Ege'de meşhur uzun hamur işi"},
    {"kelime": "MANTI", "ipucu": "Yoğurtlu ve sarımsaklı küçük hamur taneleri"},
    {"kelime": "KÖFTE", "ipucu": "Yoğrulup ızgarada pişirilen kıyma topu"},
    {"kelime": "BÖREK", "ipucu": "Yufkadan yapılan peynirli veya kıymalı hamur işi"},
    {"kelime": "SİMİT", "ipucu": "Halkalı ve susamlı çıtır sokak lezzeti"},
    {"kelime": "POĞAÇA", "ipucu": "Mayalı yumuşak kahvaltılık çörek"},
    {"kelime": "REÇEL", "ipucu": "Meyvelerin şekerle kaynatılmasıyla yapılan tatlı"},
    {"kelime": "PEYNİR", "ipucu": "Sütten yapılan kahvaltılık temel gıda"},
    {"kelime": "ZEYTİN", "ipucu": "Kahvaltı sofralarının siyah ve yeşil taneli lezzeti"},
    {"kelime": "YUMURTA", "ipucu": "Tavuktan elde edilen yüksek proteinli gıda"},
    {"kelime": "TEREYAĞI", "ipucu": "Yoğurttan elde edilen doğal yağ"},
    {"kelime": "YOĞURT", "ipucu": "Mayalanmış sütten elde edilen beyaz gıda"},
    {"kelime": "AYRAN", "ipucu": "Yoğurdun sulandırılmasıyla yapılan ferahlatıcı içecek"},
    {"kelime": "ŞALGAM", "ipucu": "Adana'ya özgü mor renkli acılı içecek"},
    {"kelime": "BOZA", "ipucu": "Kışın içilen darıdan yapılan geleneksel içecek"},
    {"kelime": "SALEP", "ipucu": "Kışın tarançınla içilen sıcak sütlü içecek"},
    {"kelime": "DONDURMA", "ipucu": "Maraş ile özdeşleşmiş soğuk tatlı"},
    {"kelime": "KÜNEFE", "ipucu": "Hatay'ın kadayıflı ve peynirli sıcak tatlısı"},
    {"kelime": "LOKUM", "ipucu": "Yumuşak ve küp şeklinde Türk tatlısı"},
    {"kelime": "HELVACILIK", "ipucu": "Tahin ve şekerden tatlı yapma sanatı"},
    {"kelime": "CEVİZ", "ipucu": "Sert kabuklu beyne benzeyen kuruyemiş"},
    {"kelime": "FINDIK", "ipucu": "Karadeniz'in simgesi sert kabuklu çerez"},
    {"kelime": "FISTIK", "ipucu": "Gaziantep veya Siirt ile anılan yeşil kuruyemiş"},
    {"kelime": "BADEM", "ipucu": "Sert kabuklu oval lezzetli kuruyemiş"},
    {"kelime": "KESTANE", "ipucu": "Sokaklarda közlenen kış yemişi"},
    {"kelime": "İNCİR", "ipucu": "Aydın ilimizin meşhur tatlı meyvesi"},
    {"kelime": "ÜZÜM", "ipucu": "Salkım şeklinde yetişen ve kurutulan meyve"},
    {"kelime": "KAYISI", "ipucu": "Malatya'nın turuncu renkli meşhur meyvesi"},
    {"kelime": "ŞEFTALİ", "ipucu": "Bursa'nın tüylü ve sulu meyvesi"},
    {"kelime": "ELMA", "ipucu": "Amasya ile özdeşleşmiş kırmızı yeşil meyve"},
    {"kelime": "ARMUT", "ipucu": "Sulu ve tatlı bir ağaç meyvesi"},
    {"kelime": "PORTAKAL", "ipucu": "C vitamini deposu narenciye meyvesi"},
    {"kelime": "MANDALİNA", "ipucu": "Kabuğu kolay soyulan küçük narenciye"},
    {"kelime": "LİMON", "ipucu": "Çorbaya ve salataya sıkılan ekşi sarı meyve"},
    {"kelime": "KARPUZ", "ipucu": "Diyarbakır'ın devasa yeşil ve içi kırmızı meyvesi"},
    {"kelime": "KAVUN", "ipucu": "Sarı kabuklu güzel kokulu yaz meyvesi"},
    {"kelime": "ÇİLEK", "ipucu": "Kırmızı pütürlü ve güzel kokulu yaz meyvesi"},
    {"kelime": "MUZ", "ipucu": "Anamur'da yetişen sarı uzun meyve"},
    {"kelime": "ANANAS", "ipucu": "Dikenli kabuklu tropikal büyük meyve"},
    {"kelime": "AVOKADO", "ipucu": "Yeşil kabuklu ve çekirdekli yağlı tropikal meyve"},
    {"kelime": "DOMATES", "ipucu": "Kırmızı renkli salça yapımında kullanılan sebze"},
    {"kelime": "SALATALIK", "ipucu": "Yeşil renkli ferahlatıcı cacık malzemesi"},
    {"kelime": "PATLICAN", "ipucu": "Karnıyarık yemeğinin ana malzemesi mor sebze"},
    {"kelime": "BİBER", "ipucu": "Acı veya tatlı olabilen yeşil/kırmızı sebze"},
    {"kelime": "PATATES", "ipucu": "Kızartması ve püresi çok sevilen yumru sebze"},
    {"kelime": "SOĞAN", "ipucu": "Yemeklerin temel harcı olan ve göz yaşartan sebze"},
    {"kelime": "SARIMSAK", "ipucu": "Doğal antibiyotik sayılan keskin kokulu sebze"},
    {"kelime": "HAVUÇ", "ipucu": "Tavşanların çok sevdiği turuncu kök sebze"},
    {"kelime": "ISPANAK", "ipucu": "Temel Reis'e güç veren demir deposu yeşillik"},
    {"kelime": "PIRASA", "ipucu": "Zeytinyağlısı yapılan katmanlı sebze"},
    {"kelime": "KABAK", "ipucu": "Tatlısı ve dolması yapılan yeşil/turuncu sebze"},
    {"kelime": "BEZELYE", "ipucu": "Yeşil taneli yuvarlak sebze"},
    {"kelime": "FASULYE", "ipucu": "Kuru ve taze olarak pişirilen milli yemeğimiz"},
    {"kelime": "MERCİMEK", "ipucu": "Kırmızı ve yeşil türü olan çorbalık bakliyat"},
    {"kelime": "NOHUT", "ipucu": "Hümüsün ve eti yemeğin ana maddesi bakliyat"},
    {"kelime": "PİRİNÇ", "ipucu": "Pilavın ana malzemesi beyaz tane"},
    {"kelime": "BULGUR", "ipucu": "Buğdaydan elde edilen besleyici pilavlık tane"},
    {"kelime": "BUĞDAY", "ipucu": "Unun ve ekmeğin hammaddesi olan tahıl"},
    {"kelime": "ARPA", "ipucu": "Tahıl ve yem bitkisi"},
    {"kelime": "MISIR", "ipucu": "Patlamışı sinemada yenen sarı taneli tahıl"},
    {"kelime": "YULAF", "ipucu": "Diyetlerde tüketilen lifli tahıl"},
    {"kelime": "EKMEK", "ipucu": "Sofraların vazgeçilmez temel gıdası"}
]

active_games = {}

# =========================================================
# DİL ALGILAMA
# =========================================================

def detect_language(text: str) -> str:
    """Mesajdaki Kiril alfabesini kontrol ederek Rusça mı Türkçe mi anlar."""
    cyrillic_chars = set("абвгдеёжзийклмнопрстуфхцчшщъыьэюя")
    if any(char.lower() in cyrillic_chars for char in text):
        return "ru"
    return "tr"

# =========================================================
# BOT KOMUTLARI
# =========================================================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text if update.message else ""
    lang = detect_language(user_text)
    
    if lang == "ru":
        msg = (
            "🤖 **Добро пожаловать в Viyana AI!**\n\n"
            "Автоперевод + ИИ-ассистент активны.\n\n"
            "📌 Популярные команды:\n"
            "• /viana <вопрос> — Чат с ИИ\n"
            "• /burc kova — Гороскоп\n"
            "• /oyun — Игра в слова\n"
            "• /gunluk — Ежедневный бонус\n"
            "• /coin — Баланс\n"
            "• /help — Все команды\n"
            "• /hakkinda — О боте\n\n"
            "🌐 Сообщения автоматически переводятся (TR ⇆ RU)"
        )
    else:
        msg = (
            "🤖 **Viyana AI'ya Hoş Geldiniz!**\n\n"
            "Otomatik çeviri + Yapay Zeka asistanı aktif.\n\n"
            "📌 Popüler komutlar:\n"
            "• /viana <soru> — AI ile sohbet et\n"
            "• /burc kova — Burç yorumu\n"
            "• /oyun — Kelime oyunu\n"
            "• /gunluk — Günlük ödül\n"
            "• /coin — Bakiyen\n"
            "• /help — Tüm komutlar\n"
            "• /hakkinda — Bot hakkında\n\n"
            "🌐 Mesajlar otomatik çevrilir (TR ⇆ RU)"
        )
    
    await update.message.reply_text(msg, parse_mode="Markdown")

async def profil_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    lang = detect_language(update.message.text)

    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT xp, level, coins, title FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()

    if row is None:
        xp, level, coins, title = 0, 1, 100, "Yeni Üye / Новичок"
    else:
        xp, level, coins, title = row

    if lang == "ru":
        msg = (
            f"👤 **Профиль пользователя:** {update.effective_user.first_name}\n\n"
            f"⭐ **Уровень:** {level}\n"
            f"✨ **XP:** {xp}\n"
            f"🪙 **Монеты:** {coins}\n"
            f"🏅 **Титул:** {title}"
        )
    else:
        msg = (
            f"👤 **Kullanıcı Profili:** {update.effective_user.first_name}\n\n"
            f"⭐ **Seviye:** {level}\n"
            f"✨ **XP:** {xp}\n"
            f"🪙 **Coin:** {coins}\n"
            f"🏅 **Unvan:** {title}"
        )
    
    await update.message.reply_text(msg, parse_mode="Markdown")

async def gunluk_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    now = int(time.time())
    lang = detect_language(update.message.text)

    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT last_daily FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()

    if row and (now - row[0] < 86400):
        remaining = int((86400 - (now - row[0])) / 3600)
        conn.close()
        if lang == "ru":
            await update.message.reply_text(f"⏳ Вы уже забирали бонус! Приходите через {remaining} часов.")
        else:
            await update.message.reply_text(f"⏳ Günlük ödülünü zaten aldın! {remaining} saat sonra tekrar gel.")
        return

    cursor.execute("UPDATE users SET last_daily = ? WHERE user_id = ?", (now, user_id))
    conn.commit()
    conn.close()

    add_xp_and_coins(user_id, chat_id, xp_amount=50, coin_amount=50)

    if lang == "ru":
        await update.message.reply_text("🎁 **Ежедневный бонус получен!**\nПолучено: +50 XP и +50 Монет!", parse_mode="Markdown")
    else:
        await update.message.reply_text("🎁 **Günlük Ödül Alındı!**\nKazandın: +50 XP ve +50 Coin!", parse_mode="Markdown")

async def mahkeme_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = detect_language(update.message.text)
    
    if not update.message.reply_to_message:
        if lang == "ru":
            await update.message.reply_text("⚠️ Ответьте на сообщение пользователя, которого хотите судить!")
        else:
            await update.message.reply_text("⚠️ Mahkemeye çıkarmak istediğiniz kişinin mesajını yanıtlayarak (reply) yazın!")
        return

    sanik = update.message.reply_to_message.from_user.first_name
    davaci = update.message.from_user.first_name

    kararlar_tr = [
        f"👨‍⚖️ **MAHKEME KARARI:**\n{sanik}, {davaci} tarafından suçlu bulundu! Cezası: Gruba 100 mesaj atmak!",
        f"👨‍⚖️ **MAHKEME KARARI:**\n{sanik} Masum ilan edildi! {davaci} mahkeme masraflarını ödeyecek.",
        f"👨‍⚖️ **MAHKEME KARARI:**\n{sanik} 1 gün boyunca grupta 'Ben suçluyum' diye gezecek!"
    ]
    
    kararlar_ru = [
        f"👨‍⚖️ **РЕШЕНИЕ СУДА:**\n{sanik} признан виновным по иску {davaci}! Наказание: Написать 100 сообщений в группу!",
        f"👨‍⚖️ **РЕШЕНИЕ СУДА:**\n{sanik} признан невиновным! {davaci} оплачивает судебные издержки.",
        f"👨‍⚖️ **РЕШЕНИЕ СУДА:**\n{sanik} обязан 1 день писать 'Я виновен' в чате!"
    ]

    karar = random.choice(kararlar_ru if lang == "ru" else kararlar_tr)
    await update.message.reply_text(karar, parse_mode="Markdown")

async def burc_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = detect_language(update.message.text if update.message else "")
    args = context.args
    burc_adi = " ".join(args).strip().lower() if args else ""

    # Burç isimleri eşleştirme
    burclar = {
        "koc": "Koç", "koç": "Koç", "aries": "Koç",
        "boga": "Boğa", "boğa": "Boğa", "taurus": "Boğa",
        "ikizler": "İkizler", "gemini": "İkizler",
        "yengec": "Yengeç", "yengeç": "Yengeç", "cancer": "Yengeç",
        "aslan": "Aslan", "leo": "Aslan",
        "basak": "Başak", "başak": "Başak", "virgo": "Başak",
        "terazi": "Terazi", "libra": "Terazi",
        "akrep": "Akrep", "scorpio": "Akrep",
        "yay": "Yay", "sagittarius": "Yay",
        "oglak": "Oğlak", "oğlak": "Oğlak", "capricorn": "Oğlak",
        "kova": "Kova", "aquarius": "Kova",
        "balik": "Balık", "balık": "Balık", "pisces": "Balık",
    }

    # Rastgele yorum havuzları (burç özel + genel)
    yorumlar_tr = {
        "Koç": [
            "Bugün enerjiniz çok yüksek Koç! Cesur adımlar atmaya hazır olun.",
            "Rekabet sizin alanınız, bugün öne çıkabilirsiniz.",
            "Aşkta ateşli bir gün sizi bekliyor, duygularınızı açıkça ifade edin."
        ],
        "Boğa": [
            "Maddi konularda dikkatli olun Boğa, sabırlı olmanın zamanı.",
            "Konfor alanınızdan çıkmak size iyi gelebilir.",
            "Lezzetli yemekler ve rahatlık bugün sizi mutlu edecek."
        ],
        "İkizler": [
            "İletişim gücünüz zirvede İkizler, yeni insanlarla tanışın.",
            "Zihniniz çok aktif, fikirlerinizi not alın.",
            "Kısa yolculuklar veya mesajlaşmalar gününüze renk katacak."
        ],
        "Yengeç": [
            "Duygusal derinliklerinizde yüzüyorsunuz Yengeç, eviniz sığınak olsun.",
            "Aile ve sevdiklerinizle vakit geçirmek size iyi gelecek.",
            "Sezgileriniz çok güçlü, iç sesinizi dinleyin."
        ],
        "Aslan": [
            "Sahneye çıkma zamanı Aslan! Işıltınız herkesi etkileyecek.",
            "Liderlik özellikleriniz bugün öne çıkıyor.",
            "Romantik sürprizlere açık olun, kalbinizi dinleyin."
        ],
        "Başak": [
            "Detaylara odaklanın Başak, mükemmeliyetçiliğiniz işe yarayacak.",
            "Sağlık ve düzen konularında kendinize zaman ayırın.",
            "Pratik çözümleriniz çevrenizdekileri etkileyecek."
        ],
        "Terazi": [
            "Denge ve uyum arayışınız bugün karşılık bulacak Terazi.",
            "İlişkilerinizde diplomasi sizin silahınız.",
            "Güzellik ve sanat sizi motive edecek."
        ],
        "Akrep": [
            "Derin dönüşümler zamanı Akrep, eskiyi bırakın.",
            "Tutkularınız güçlü, kontrolü elden bırakmayın.",
            "Gizemli bir çekim alanı yaratıyorsunuz."
        ],
        "Yay": [
            "Özgürlük ve macera sizi çağırıyor Yay!",
            "Yeni bilgilere açık olun, ufkunuz genişliyor.",
            "İyimserliğiniz çevrenize bulaşıcı olacak."
        ],
        "Oğlak": [
            "Hedeflerinize emin adımlarla ilerleyin Oğlak.",
            "Disiplin ve sorumluluk bugün sizi ödüllendirecek.",
            "Kariyerde önemli bir adım atabilirsiniz."
        ],
        "Kova": [
            "Yenilikçi fikirleriniz parlıyor Kova! Farklı olun.",
            "Arkadaşlıklar ve topluluklar size güç verecek.",
            "Teknoloji ve gelecek odaklı düşünceler sizi motive ediyor.",
            "Bugün enerjiniz çok yüksek Kova, sürpriz gelişmelere hazır olun!",
            "Bağımsızlığınızı koruyun, kimse sizi sınırlayamasın."
        ],
        "Balık": [
            "Hayal gücünüz ve sezgileriniz zirvede Balık.",
            "Sanat, müzik veya rüyalar size ilham verecek.",
            "Duygusal bağlarınız güçleniyor, empati yapın."
        ],
        "genel": [
            "Bugün enerjiniz çok yüksek, sürpriz gelişmelere hazır olun!",
            "Maddi konularda dikkatli olmanız gereken bir gün.",
            "Aşk hayatınızda hareketlenme var, gözlerinizi açık tutun!",
            "Kariyerinizde yeni fırsatlar kapınızı çalabilir.",
            "İç sesinizi dinleyin, sezgileriniz sizi doğru yönlendirecek."
        ]
    }

    yorumlar_ru = {
        "Koç": ["Сегодня ваша энергия на пике, Овен! Будьте смелыми.", "Конкуренция — ваша стихия сегодня."],
        "Boğa": ["Будьте осторожны с финансами, Телец. Терпение — ваш ключ."],
        "İkizler": ["Ваша коммуникация на высоте, Близнецы. Знакомьтесь с новыми людьми."],
        "Yengeç": ["Эмоциональная глубина — ваша сила сегодня, Рак."],
        "Aslan": ["Время выйти на сцену, Лев! Вы сияете."],
        "Başak": ["Внимание к деталям принесёт успех, Дева."],
        "Terazi": ["Баланс и гармония рядом, Весы."],
        "Akrep": ["Глубокая трансформация ждёт вас, Скорпион."],
        "Yay": ["Свобода и приключения зовут, Стрелец!"],
        "Oğlak": ["Целеустремленность приведёт к успеху, Козерог."],
        "Kova": [
            "Ваши инновационные идеи сияют, Водолей!",
            "Дружба и сообщество дадут вам силу.",
            "Сегодня у вас отличная энергия, Водолей — готовьтесь к сюрпризам!"
        ],
        "Balık": ["Воображение и интуиция на пике, Рыбы."],
        "genel": [
            "Сегодня у вас отличная энергия, будьте готовы к сюрпризам!",
            "Будьте осторожны с финансами сегодня.",
            "В личной жизни намечаются перемены, держите глаза открытыми!",
            "В карьере могут открыться новые возможности."
        ]
    }

    if burc_adi and burc_adi in burclar:
        burc_key = burclar[burc_adi]
        pool = (yorumlar_ru if lang == "ru" else yorumlar_tr).get(burc_key, yorumlar_tr["genel"])
        yorum = random.choice(pool)
        if lang == "ru":
            await update.message.reply_text(f"🔮 **Гороскоп — {burc_key}:**\n{yorum}", parse_mode="Markdown")
        else:
            await update.message.reply_text(f"🔮 **Günlük Burç — {burc_key}:**\n{yorum}", parse_mode="Markdown")
    else:
        # Argüman yoksa veya geçersizse genel + kullanım bilgisi
        pool = yorumlar_ru["genel"] if lang == "ru" else yorumlar_tr["genel"]
        yorum = random.choice(pool)
        if lang == "ru":
            await update.message.reply_text(
                f"🔮 **Гороскоп на сегодня:**\n{yorum}\n\n"
                f"_Использование: /burc kova  |  /burc aslan_",
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(
                f"🔮 **Günlük Burç Yorumunuz:**\n{yorum}\n\n"
                f"_Kullanım: /burc kova  |  /burc aslan  |  /burc terazi_",
                parse_mode="Markdown"
            )

async def liderlik_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = detect_language(update.message.text)
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, level, xp FROM users ORDER BY level DESC, xp DESC LIMIT 5")
    rows = cursor.fetchall()
    conn.close()

    if lang == "ru":
        msg = "🏆 **Таблица лидеров:**\n\n"
    else:
        msg = "🏆 **Liderlik Tablosu:**\n\n"

    for idx, row in enumerate(rows, 1):
        msg += f"{idx}. ID: {row[0]} — Level: {row[1]} ({row[2]} XP)\n"

    await update.message.reply_text(msg, parse_mode="Markdown")

# =========================================================
# KELİME OYUNU SİSTEMİ
# =========================================================

async def oyun_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    lang = detect_language(update.message.text if update.message else "")
    args = [a.lower() for a in (context.args or [])]

    # /oyun iptal  veya  /oyun stop  → mevcut oyunu zorla bitir
    if args and args[0] in ("iptal", "stop", "iptalet", "cancel", "bitir"):
        if chat_id in active_games:
            kelime = active_games[chat_id]["kelime"]
            del active_games[chat_id]
            if lang == "ru":
                await update.message.reply_text(f"🛑 Игра отменена.\nСлово было: **{kelime}**", parse_mode="Markdown")
            else:
                await update.message.reply_text(f"🛑 Oyun iptal edildi.\nDoğru kelime: **{kelime}**", parse_mode="Markdown")
        else:
            if lang == "ru":
                await update.message.reply_text("ℹ️ Активной игры нет.")
            else:
                await update.message.reply_text("ℹ️ Devam eden bir oyun yok.")
        return

    # Eski / takılı kalmış oyun kontrolü (70 saniyeden eskiyse otomatik temizle)
    if chat_id in active_games:
        game = active_games[chat_id]
        age = time.time() - game.get("start_time", 0)
        if age > 70:
            del active_games[chat_id]
            # devam et, yeni oyun başlat
        else:
            kalan = max(0, int(60 - age))
            if lang == "ru":
                await update.message.reply_text(
                    f"⚠️ Игра уже идет! Осталось ~{kalan} сек.\n"
                    f"Отменить: `/oyun iptal`",
                    parse_mode="Markdown"
                )
            else:
                await update.message.reply_text(
                    f"⚠️ Zaten devam eden bir oyun var! Kalan süre ~{kalan} sn.\n"
                    f"İptal etmek için: `/oyun iptal`",
                    parse_mode="Markdown"
                )
            return

    item = random.choice(KELIME_HAVUZU)
    kelime = item["kelime"].upper()
    ipucu = item["ipucu"]

    masked = ["_" for _ in kelime]

    active_games[chat_id] = {
        "kelime": kelime,
        "ipucu": ipucu,
        "masked": masked,
        "start_time": time.time(),
        "chat_id": chat_id
    }

    keyboard = [
        [
            InlineKeyboardButton("💡 Harf Aç", callback_data="harf_ac"),
            InlineKeyboardButton("🛑 İptal", callback_data="oyun_iptal")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if lang == "ru":
        txt = (
            f"🎮 **Словесная игра началась!**\n\n"
            f"📝 **Подсказка:** {ipucu}\n"
            f"🔤 **Слово:** {' '.join(masked)}\n"
            f"⏳ **Время:** 60 секунд!\n"
            f"_Отмена: /oyun iptal_"
        )
    else:
        txt = (
            f"🎮 **Kelime Oyunu Başladı!**\n\n"
            f"📝 **İpucu:** {ipucu}\n"
            f"🔤 **Kelime:** {' '.join(masked)}\n"
            f"⏳ **Süre:** 60 Saniye!\n"
            f"_İptal: /oyun iptal_"
        )

    msg = await update.message.reply_text(txt, reply_markup=reply_markup, parse_mode="Markdown")
    asyncio.create_task(game_timer(context, chat_id, msg.message_id, lang))

async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat.id
    data = query.data

    if chat_id not in active_games:
        await query.edit_message_text("⚠️ Bu oyun artık aktif değil.")
        return

    game = active_games[chat_id]
    kelime = game["kelime"]
    masked = game["masked"]

    # İptal butonu
    if data == "oyun_iptal":
        del active_games[chat_id]
        await query.edit_message_text(
            f"🛑 Oyun iptal edildi.\nDoğru kelime: **{kelime}**",
            parse_mode="Markdown"
        )
        return

    # Harf aç
    unopened = [i for i, char in enumerate(masked) if char == "_"]
    if unopened:
        idx = random.choice(unopened)
        masked[idx] = kelime[idx]
        game["masked"] = masked

    # Hepsi açıldıysa bitir
    if "_" not in masked:
        del active_games[chat_id]
        await query.edit_message_text(
            f"🎉 Kelime tamamlandı: **{kelime}**",
            parse_mode="Markdown"
        )
        return

    keyboard = [
        [
            InlineKeyboardButton("💡 Harf Aç", callback_data="harf_ac"),
            InlineKeyboardButton("🛑 İptal", callback_data="oyun_iptal")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    txt = (
        f"🎮 **Kelime Tahmin Oyunu**\n\n"
        f"📝 **İpucu:** {game['ipucu']}\n"
        f"🔤 **Kelime:** {' '.join(masked)}"
    )
    await query.edit_message_text(txt, reply_markup=reply_markup, parse_mode="Markdown")

async def game_timer(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int, lang: str):
    try:
        await asyncio.sleep(60)
        if chat_id in active_games:
            # Sadece bu oyunun timer'ıysa sil (start_time kontrolü ile daha güvenli)
            game = active_games.get(chat_id)
            if not game:
                return
            # 55 saniyeden eskiyse süre dolmuş kabul et
            if time.time() - game.get("start_time", 0) >= 55:
                kelime = game["kelime"]
                del active_games[chat_id]
                if lang == "ru":
                    txt = f"⏰ **Время вышло!** Никто не угадал слово.\nПравильное слово: **{kelime}**"
                else:
                    txt = f"⏰ **Süre Doldu!** Kimse kelimeyi bilemedi.\nDoğru Kelime: **{kelime}**"
                await context.bot.send_message(chat_id=chat_id, text=txt, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"game_timer hatası: {e}")
        # Takılı kalmasın diye yine de temizle
        if chat_id in active_games:
            del active_games[chat_id]

# =========================================================
# OTOMATİK ÇEVİRİ VE MESAJ DİNLEYİCİ
# =========================================================

async def handle_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    text = update.message.text.strip()

    # 1. Oyun Kontrolü
    if chat_id in active_games:
        game = active_games[chat_id]
        if text.upper() == game["kelime"]:
            del active_games[chat_id]
            add_xp_and_coins(user_id, chat_id, xp_amount=30, coin_amount=20)
            
            lang = detect_language(text)
            if lang == "ru":
                await update.message.reply_text(
                    f"🎉 **Поздравляем {update.effective_user.first_name}!** Вы угадали слово!\n"
                    f"Награда: +30 XP и +20 Монет!", parse_mode="Markdown"
                )
            else:
                await update.message.reply_text(
                    f"🎉 **Tebrikler {update.effective_user.first_name}!** Kelimeyi doğru bildin!\n"
                    f"Kazandın: +30 XP ve +20 Coin!", parse_mode="Markdown"
                )
            return

    # 2. XP Ekleme
    add_xp_and_coins(user_id, chat_id, xp_amount=2, coin_amount=1)

    # 3. Otomatik Çeviri (OpenAI)
    if len(text) > 2 and not text.startswith("/") and client:
        try:
            detected_lang = detect_language(text)
            
            if detected_lang == "ru":
                target_lang = "Turkish"
                prefix = "🇹🇷 **Çeviri (TR):**"
            else:
                target_lang = "Russian"
                prefix = "🇷🇺 **Перевод (RU):**"

            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": f"You are a professional translator. Translate the given text to {target_lang}. Only return the translated text, nothing else."
                    },
                    {
                        "role": "user",
                        "content": text
                    }
                ],
                temperature=0.2,
                max_tokens=1000
            )
            translated = response.choices[0].message.content.strip()
            
            if translated and translated.lower().strip() != text.lower().strip():
                await update.message.reply_text(f"{prefix} {translated}", parse_mode="Markdown")
                
        except Exception as e:
            logger.error(f"Çeviri hatası: {e}")


async def hakkinda_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = detect_language(update.message.text if update.message else "")
    
    if lang == "ru":
        msg = (
            "🤖 **О боте Viyana AI**\n\n"
            "Я — автоматический переводчик и ИИ-ассистент.\n"
            "Создан **Ehed**."
        )
    else:
        msg = (
            "🤖 **Viyana AI Hakkında**\n\n"
            "Ben otomatik çeviri ve Yapay Zeka Asistan botuyum.\n"
            "**Ehed** tarafından tasarlandım."
        )
    
    await update.message.reply_text(msg, parse_mode="Markdown")


# =========================================================
# EK KOMUTLAR
# =========================================================

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = detect_language(update.message.text if update.message else "")
    if lang == "ru":
        msg = (
            "📖 **Список команд Viyana AI**\n\n"
            "• /start — Главное меню\n"
            "• /viana <вопрос> — Спросить ИИ-ассистента\n"
            "• /help — Эта справка\n"
            "• /oyun или /kelime — Игра в слова\n"
            "• /hakkinda — О боте\n"
            "• /coin — Баланс монет\n"
            "• /seviye или /profil — Уровень и XP\n"
            "• /gunluk — Ежедневный бонус\n"
            "• /liderlik — Таблица лидеров\n"
            "• /das — Орёл/решка (ставка)\n"
            "• /burc <знак> — Гороскоп (пример: /burc kova)\n"
            "• /mahkeme — Суд (ответьте на сообщение)\n"
            "• /giybet — Случайные сплетни\n"
            "• /lakaptak — Случайный никнейм\n"
            "• /ban /sus — Только для админов\n"
            "• /panel — Панель управления группой"
        )
    else:
        msg = (
            "📖 **Viyana AI Komut Listesi**\n\n"
            "• /start — Ana menü\n"
            "• /viana <soru> — Yapay zeka asistanına sor\n"
            "• /help — Bu yardım menüsü\n"
            "• /oyun veya /kelime — Kelime tahmin oyunu\n"
            "• /hakkinda — Bot hakkında\n"
            "• /coin — Coin bakiyen\n"
            "• /seviye veya /profil — Seviye, XP ve unvan\n"
            "• /gunluk — Günlük ödül\n"
            "• /liderlik — Liderlik tablosu\n"
            "• /das — Yazı tura / coin bahis\n"
            "• /burc <burç> — Burç yorumu (örnek: /burc kova)\n"
            "• /mahkeme — Mahkeme (bir mesaja yanıt vererek)\n"
            "• /giybet — Rastgele dedikodu\n"
            "• /lakaptak — Rastgele lakap\n"
            "• /ban /sus — Sadece yöneticiler\n"
            "• /panel — Grup yönetim paneli"
        )
    await update.message.reply_text(msg, parse_mode="Markdown")


async def viana_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Yapay zeka sohbet / soru-cevap"""
    if not client:
        await update.message.reply_text("⚠️ OpenAI API anahtarı tanımlı değil.")
        return

    soru = " ".join(context.args).strip() if context.args else ""
    if not soru:
        # Reply edilen mesaj varsa onu al
        if update.message.reply_to_message and update.message.reply_to_message.text:
            soru = update.message.reply_to_message.text
        else:
            await update.message.reply_text(
                "💬 **Viyana AI Asistan**\n\n"
                "Kullanım: `/viana merhaba nasılsın?`\n"
                "veya bir mesaja yanıt verip `/viana` yaz.",
                parse_mode="Markdown"
            )
            return

    try:
        await update.message.chat.send_action(action="typing")
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Sen Viyana AI adında eğlenceli, yardımsever ve zeki bir Telegram bot asistanısın. "
                        "Türkçe ve Rusça konuşabiliyorsun. Kısa, samimi ve esprili cevaplar ver. "
                        "Ehed tarafından tasarlandın. Çok uzun cevaplar verme."
                    )
                },
                {"role": "user", "content": soru}
            ],
            temperature=0.7,
            max_tokens=600
        )
        cevap = response.choices[0].message.content.strip()
        await update.message.reply_text(f"🤖 **Viyana AI:**\n{cevap}", parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Viana AI hatası: {e}")
        await update.message.reply_text("⚠️ Şu an cevap veremiyorum, biraz sonra tekrar dene.")


async def coin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = detect_language(update.message.text if update.message else "")
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT coins FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    coins = row[0] if row else 100
    if lang == "ru":
        await update.message.reply_text(f"🪙 **Ваш баланс:** {coins} монет", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"🪙 **Coin Bakiyen:** {coins} coin", parse_mode="Markdown")


async def seviye_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # profil ile aynı
    await profil_command(update, context)


async def das_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Yazı tura / coin bahis"""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    lang = detect_language(update.message.text if update.message else "")
    args = context.args

    bahis = 10
    secim = None
    if args:
        try:
            bahis = int(args[0])
        except ValueError:
            secim = args[0].lower()
            if len(args) > 1:
                try:
                    bahis = int(args[1])
                except ValueError:
                    pass

    if secim not in ("yazi", "yazı", "tura", "орёл", "решка", "yazi", "tura"):
        secim = random.choice(["yazi", "tura"])

    # Normalize
    if secim in ("yazi", "yazı", "орёл"):
        secim = "yazi"
    else:
        secim = "tura"

    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT coins FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if row is None:
        cursor.execute(
            "INSERT INTO users (user_id, chat_id, xp, level, coins) VALUES (?, ?, 0, 1, 100)",
            (user_id, chat_id)
        )
        coins = 100
    else:
        coins = row[0]
    conn.commit()
    conn.close()

    if coins < bahis:
        if lang == "ru":
            await update.message.reply_text(f"💸 Недостаточно монет! У вас {coins}.")
        else:
            await update.message.reply_text(f"💸 Yeterli coinin yok! Bakiyen: {coins}")
        return

    sonuc = random.choice(["yazi", "tura"])
    kazandi = (sonuc == secim)

    if kazandi:
        add_xp_and_coins(user_id, chat_id, xp_amount=5, coin_amount=bahis)
        if lang == "ru":
            await update.message.reply_text(
                f"🎲 Выпало: **{'орёл' if sonuc=='yazi' else 'решка'}**\n"
                f"✅ Вы выиграли +{bahis} монет!",
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(
                f"🎲 Sonuç: **{'Yazı' if sonuc=='yazi' else 'Tura'}**\n"
                f"✅ Tebrikler! +{bahis} coin kazandın!",
                parse_mode="Markdown"
            )
    else:
        # kaybettir
        conn = sqlite3.connect("database.db")
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET coins = coins - ? WHERE user_id = ?", (bahis, user_id))
        conn.commit()
        conn.close()
        if lang == "ru":
            await update.message.reply_text(
                f"🎲 Выпало: **{'орёл' if sonuc=='yazi' else 'решка'}**\n"
                f"❌ Вы проиграли {bahis} монет.",
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(
                f"🎲 Sonuç: **{'Yazı' if sonuc=='yazi' else 'Tura'}**\n"
                f"❌ Maalesef {bahis} coin kaybettin.",
                parse_mode="Markdown"
            )


async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = detect_language(update.message.text if update.message else "")
    user = update.effective_user
    chat = update.effective_chat

    if chat.type == "private":
        await update.message.reply_text("Bu komut sadece gruplarda çalışır.")
        return

    # Yönetici kontrolü
    try:
        member = await chat.get_member(user.id)
        if member.status not in ("administrator", "creator"):
            if lang == "ru":
                await update.message.reply_text("⛔ Только администраторы могут использовать эту команду.")
            else:
                await update.message.reply_text("⛔ Bu komutu sadece yöneticiler kullanabilir.")
            return
    except Exception:
        await update.message.reply_text("Yetki kontrolü yapılamadı.")
        return

    target = None
    if update.message.reply_to_message:
        target = update.message.reply_to_message.from_user
    elif context.args:
        # basit ID denemesi
        try:
            target_id = int(context.args[0])
            target = await context.bot.get_chat(target_id)
        except Exception:
            pass

    if not target:
        if lang == "ru":
            await update.message.reply_text("Использование: ответьте на сообщение пользователя командой /ban")
        else:
            await update.message.reply_text("Kullanım: Yasaklamak istediğin kişinin mesajına yanıt verip /ban yaz.")
        return

    try:
        await chat.ban_member(target.id)
        if lang == "ru":
            await update.message.reply_text(f"🚫 Пользователь {target.first_name} забанен.")
        else:
            await update.message.reply_text(f"🚫 {target.first_name} gruptan yasaklandı.")
    except Exception as e:
        await update.message.reply_text(f"Ban işlemi başarısız: {e}")


async def sus_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kullanıcıyı sustur (mute)"""
    lang = detect_language(update.message.text if update.message else "")
    user = update.effective_user
    chat = update.effective_chat

    if chat.type == "private":
        await update.message.reply_text("Bu komut sadece gruplarda çalışır.")
        return

    try:
        member = await chat.get_member(user.id)
        if member.status not in ("administrator", "creator"):
            if lang == "ru":
                await update.message.reply_text("⛔ Только администраторы.")
            else:
                await update.message.reply_text("⛔ Bu komutu sadece yöneticiler kullanabilir.")
            return
    except Exception:
        return

    target = None
    if update.message.reply_to_message:
        target = update.message.reply_to_message.from_user

    if not target:
        await update.message.reply_text("Susturmak istediğin kişinin mesajına yanıt verip /sus yaz.")
        return

    from datetime import datetime, timedelta, timezone
    until = datetime.now(timezone.utc) + timedelta(hours=1)

    try:
        await context.bot.restrict_chat_member(
            chat_id=chat.id,
            user_id=target.id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=until
        )
        if lang == "ru":
            await update.message.reply_text(f"🔇 {target.first_name} замьючен на 1 час.")
        else:
            await update.message.reply_text(f"🔇 {target.first_name} 1 saatliğine susturuldu.")
    except Exception as e:
        await update.message.reply_text(f"Susturma başarısız: {e}")


async def panel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = detect_language(update.message.text if update.message else "")
    if lang == "ru":
        msg = (
            "🛠 **Панель управления группой**\n\n"
            "• /ban — Забанить пользователя (ответьте на сообщение)\n"
            "• /sus — Замьютить на 1 час\n"
            "• /liderlik — Топ участников\n"
            "• /mahkeme — Судебный розыгрыш\n\n"
            "_Только администраторы могут использовать moderation команды._"
        )
    else:
        msg = (
            "🛠 **Grup Yönetim Paneli**\n\n"
            "• /ban — Kullanıcıyı yasakla (mesaja yanıt ver)\n"
            "• /sus — 1 saat sustur\n"
            "• /liderlik — Liderlik tablosu\n"
            "• /mahkeme — Mahkeme simülasyonu\n\n"
            "_Moderasyon komutlarını sadece yöneticiler kullanabilir._"
        )
    await update.message.reply_text(msg, parse_mode="Markdown")


async def giybet_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = detect_language(update.message.text if update.message else "")
    target_name = None
    if update.message.reply_to_message:
        target_name = update.message.reply_to_message.from_user.first_name
    elif context.args:
        target_name = " ".join(context.args)
    else:
        target_name = update.effective_user.first_name

    dedikodular_tr = [
        f"📢 Duyduk ki {target_name} dün gece çok geç saatte online'mış...",
        f"🙊 {target_name} birine aşık olmuş ama kimseye söylemiyormuş!",
        f"👀 Grupta dolaşan söylentiye göre {target_name} gizli bir yeteneğe sahipmiş.",
        f"🤭 {target_name} son zamanlarda çok değişmiş, ne oldu acaba?",
        f"🔥 {target_name} hakkında bir sır var ama ben söylemem...",
        f"😏 {target_name} dün biriyle özel sohbet ediyormuş, kim olabilir?",
    ]
    dedikodular_ru = [
        f"📢 Говорят, {target_name} вчера очень поздно был(а) онлайн...",
        f"🙊 {target_name} в кого-то влюблён(а), но никому не говорит!",
        f"👀 По слухам у {target_name} есть тайный талант.",
        f"🤭 {target_name} в последнее время сильно изменился(ась)...",
        f"🔥 Об {target_name} есть секрет, но я не скажу...",
    ]

    dedikodu = random.choice(dedikodular_ru if lang == "ru" else dedikodular_tr)
    await update.message.reply_text(dedikodu)


async def lakaptak_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = detect_language(update.message.text if update.message else "")
    name = update.effective_user.first_name
    if update.message.reply_to_message:
        name = update.message.reply_to_message.from_user.first_name

    lakaplar_tr = [
        f"{name} — Efsane Canavar",
        f"{name} — Çılgın Fırtına",
        f"{name} — Sessiz Ninja",
        f"{name} — Kral/Kraliçe",
        f"{name} — Komik Deha",
        f"{name} — Gece Kuşu",
        f"{name} — Ateş Topu",
        f"{name} — Buz Prensi/Prensesi",
        f"{name} — Gizli Kahraman",
        f"{name} — Kaos Ustası",
    ]
    lakaplar_ru = [
        f"{name} — Легендарный Монстр",
        f"{name} — Безумный Шторм",
        f"{name} — Тихий Ниндзя",
        f"{name} — Король/Королева",
        f"{name} — Гений Юмора",
        f"{name} — Ночная Птица",
    ]

    lakap = random.choice(lakaplar_ru if lang == "ru" else lakaplar_tr)
    if lang == "ru":
        await update.message.reply_text(f"🏷 **Новый ник:** {lakap}", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"🏷 **Yeni Lakabın:** {lakap}", parse_mode="Markdown")


async def kelime_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Alias for /oyun"""
    await oyun_command(update, context)


# =========================================================
# MAIN
# =========================================================

def main():
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN değişkeni bulunamadı!")
        return

    if not OPENAI_API_KEY:
        logger.warning("OPENAI_API_KEY bulunamadı! Otomatik çeviri devre dışı kalacak.")

    init_db()

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    # Komutlar
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("viana", viana_command))
    app.add_handler(CommandHandler("hakkinda", hakkinda_command))
    app.add_handler(CommandHandler("about", hakkinda_command))
    app.add_handler(CommandHandler("profil", profil_command))
    app.add_handler(CommandHandler("seviye", seviye_command))
    app.add_handler(CommandHandler("coin", coin_command))
    app.add_handler(CommandHandler("gunluk", gunluk_command))
    app.add_handler(CommandHandler("liderlik", liderlik_command))
    app.add_handler(CommandHandler("oyun", oyun_command))
    app.add_handler(CommandHandler("kelime", kelime_command))
    app.add_handler(CommandHandler("burc", burc_command))
    app.add_handler(CommandHandler("mahkeme", mahkeme_command))
    app.add_handler(CommandHandler("das", das_command))
    app.add_handler(CommandHandler("giybet", giybet_command))
    app.add_handler(CommandHandler("lakaptak", lakaptak_command))
    app.add_handler(CommandHandler("panel", panel_command))
    app.add_handler(CommandHandler("ban", ban_command))
    app.add_handler(CommandHandler("sus", sus_command))

    # Buton Dinleyici
    app.add_handler(CallbackQueryHandler(button_click))

    # Mesaj ve Otomatik Çeviri Dinleyicisi
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_messages))

    logger.info("Viyana Bot Başarıyla Başlatıldı!")
    app.run_polling()

if __name__ == "__main__":
    main()
