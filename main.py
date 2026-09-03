import logging
import os
import random
import sqlite3
import time
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
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
            "🤖 **Добро пожаловать в Viyana Bot!**\n\n"
            "Я поддерживаю автоматический перевод и двухязычные команды!\n"
            "• /oyun — Начать словесную игру\n"
            "• /mahkeme — Судебный процесс\n"
            "• /burc <знак> — Гороскоп\n"
            "• /profil — Ваш профиль\n"
            "• /liderlik — Таблица лидеров\n"
            "• /gunluk — Ежедневный бонус\n\n"
            "🌐 **Автоперевод:** Любое сообщение в группе автоматически переводится (TR ⇆ RU)!"
        )
    else:
        msg = (
            "🤖 **Viyana Bot'a Hoş Geldiniz!**\n\n"
            "Gelişmiş çift dil ve otomatik çeviri sistemim aktif!\n"
            "• /oyun — Kelime tahmin oyunu başlatır\n"
            "• /mahkeme — Mahkeme simülasyonu\n"
            "• /burc <burç> — Günlük burç yorumu\n"
            "• /profil — Profiliniz ve seviyeniz\n"
            "• /liderlik — Liderlik tablosu\n"
            "• /gunluk — Günlük XP ve coin ödülü\n\n"
            "🌐 **Otomatik Çeviri:** Gruba yazılan her mesaj otomatik çevrilir (TR ⇆ RU)!"
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
    lang = detect_language(update.message.text)
    
    yorumlar_tr = [
        "Bugün enerjiniz çok yüksek, sürpriz gelişmelere hazır olun!",
        "Maddi konularda dikkatli olmanız gereken bir gün.",
        "Aşk hayatınızda hareketlenme var, gözlerinizi açık tutun!",
        "Kariyerinizde yeni fırsatlar kapınızı çalabilir."
    ]
    yorumlar_ru = [
        "Сегодня у вас отличная энергия, будьте готовы к сюрпризам!",
        "Будьте осторожны с финансами сегодня.",
        "В личной жизни намечаются перемены, держите глаза открытыми!",
        "В карьере могут открыться новые возможности."
    ]

    yorum = random.choice(yorumlar_ru if lang == "ru" else yorumlar_tr)
    
    if lang == "ru":
        await update.message.reply_text(f"🔮 **Гороскоп на сегодня:**\n{yorum}", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"🔮 **Günlük Burç Yorumunuz:**\n{yorum}", parse_mode="Markdown")

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
    lang = detect_language(update.message.text)

    if chat_id in active_games:
        if lang == "ru":
            await update.message.reply_text("⚠️ Игра уже идет!")
        else:
            await update.message.reply_text("⚠️ Zaten devam eden bir oyun var!")
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
        [InlineKeyboardButton("💡 Harf Aç / Подсказка", callback_data="harf_ac")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if lang == "ru":
        txt = (
            f"🎮 **Словесная игра началась!**\n\n"
            f"📝 **Подсказка:** {ipucu}\n"
            f"🔤 **Слово:** {' '.join(masked)}\n"
            f"⏳ **Время:** 60 секунд!"
        )
    else:
        txt = (
            f"🎮 **Kelime Oyunu Başladı!**\n\n"
            f"📝 **İpucu:** {ipucu}\n"
            f"🔤 **Kelime:** {' '.join(masked)}\n"
            f"⏳ **Süre:** 60 Saniye!"
        )

    msg = await update.message.reply_text(txt, reply_markup=reply_markup, parse_mode="Markdown")
    asyncio.create_task(game_timer(context, chat_id, msg.message_id, lang))

async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat.id

    if chat_id not in active_games:
        return

    game = active_games[chat_id]
    kelime = game["kelime"]
    masked = game["masked"]

    unopened = [i for i, char in enumerate(masked) if char == "_"]
    if unopened:
        idx = random.choice(unopened)
        masked[idx] = kelime[idx]

    keyboard = [[InlineKeyboardButton("💡 Harf Aç / Подсказка", callback_data="harf_ac")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    txt = (
        f"🎮 **Kelime Tahmin Oyunu**\n\n"
        f"📝 **İpucu:** {game['ipucu']}\n"
        f"🔤 **Kelime:** {' '.join(masked)}"
    )
    await query.edit_message_text(txt, reply_markup=reply_markup, parse_mode="Markdown")

async def game_timer(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int, lang: str):
    await asyncio.sleep(60)
    if chat_id in active_games:
        game = active_games[chat_id]
        kelime = game["kelime"]
        del active_games[chat_id]
        
        if lang == "ru":
            txt = f"⏰ **Время вышло!** Никто не угадал слово.\nПравильное слово: **{kelime}**"
        else:
            txt = f"⏰ **Süre Doldu!** Kimse kelimeyi bilemedi.\nDoğru Kelime: **{kelime}**"
            
        await context.bot.send_message(chat_id=chat_id, text=txt, parse_mode="Markdown")

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
                prefix = "🔤 **Çeviri (TR):**"
            else:
                target_lang = "Russian"
                prefix = "🔤 **Перевод (RU):**"

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
                await update.message.reply_text(f"{prefix} {translated}")
                
        except Exception as e:
            logger.error(f"Çeviri hatası: {e}")

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
    app.add_handler(CommandHandler("profil", profil_command))
    app.add_handler(CommandHandler("gunluk", gunluk_command))
    app.add_handler(CommandHandler("mahkeme", mahkeme_command))
    app.add_handler(CommandHandler("burc", burc_command))
    app.add_handler(CommandHandler("liderlik", liderlik_command))
    app.add_handler(CommandHandler("oyun", oyun_command))

    # Buton Dinleyici
    app.add_handler(CallbackQueryHandler(button_click))

    # Mesaj ve Otomatik Çeviri Dinleyicisi
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_messages))

    logger.info("Viyana Bot Başarıyla Başlatıldı!")
    app.run_polling()

if __name__ == "__main__":
    main()
