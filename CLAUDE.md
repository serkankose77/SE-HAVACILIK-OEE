# SE Havacılık OEE — Claude project guide

Bu dosya bu repoda çalışan Claude Code oturumları için kalıcı bağlamdır.
Lütfen yeni bir oturum açtığında önce buradaki kuralları yükle, sonra
göreve başla.

## Bağlam

- **Sahip / kullanıcı**: Serkan Köse (`serkankose77`), SE Havacılık.
- **Amaç**: 5 adet Haas CNC tezgahından MTConnect (port 8082) ile veri
  toplayıp InfluxDB 2.7'ye yazmak. Üstüne ileride OEE hesabı + arayüz
  gelecek; **şu an yalnızca veri toplama fazındayız.**
- **Kardeş repo**: [HaasCNC-Dashboard](https://github.com/serkankose77/HaasCNC-Dashboard)
  — aynı 5 tezgahın canlı durum panosu; bu repodan tamamen ayrı.

## Mimari hatırlatma

```
Haas tezgahları (192.168.1.112-116:8082)
        │  HTTP/XML (MTConnect /current)
        ▼
collector (Python, Docker)
        │  Line Protocol
        ▼
InfluxDB 2.7 (Docker, bucket=mtconnect)
```

İki konteyner `docker compose` ile aynı `oee-net` bridge ağında
çalışır. Collector InfluxDB'ye container adıyla erişir
(`http://influxdb:8086`); tezgahlara host bridge üzerinden çıkar.

## Önemli dosyalar

| Yol                             | Rol                                                             |
| ------------------------------- | --------------------------------------------------------------- |
| `machines.json`                 | Tezgah envanteri. Read-only mount. Düzenle → `restart collector`. |
| `collector/collector.py`        | Tek dosyalık polling collector. Tüm DataItem'ları yazar.        |
| `collector/Dockerfile`          | python:3.12-slim üzerinde, non-root (1000:1000) çalışır.        |
| `collector/requirements.txt`    | `requests`, `influxdb-client`. Yeni bağımlılık eklersen Dockerfile'ı yeniden build et. |
| `docker-compose.yml`            | InfluxDB + collector. Healthcheck + bağımlılık zinciri.         |
| `.env.example`                  | Şablon. `.env` `.gitignore`'da; **asla commitlenmez**.          |
| `README.md`                     | Türkçe son kullanıcı dokümanı, Flux örnekleri.                  |

## Veri şeması (kısa)

- **`mtconnect`** measurement → her DataItem bir nokta. Tag'ler:
  `machine_id`, `machine_name`, `machine_type`, `category`
  (`Events`/`Samples`/`Condition`), `item_type`, `name`, `component`,
  `sub_type?`, `condition_type?`. Field'lar: Samples için `value`
  (float), Events için `value_str` (string), Condition için `state` +
  opsiyonel `value_str`.
- **`mtconnect_status`** measurement → her döngüde
  `reachable=true|false`. Availability hesapları için bunu kullan.

Şemayı değiştireceksen mevcut kullanıcının InfluxDB bucket'ında
geçmiş veri olabileceğini unutma — `category`/`name` tag'lerini
yeniden adlandırmak Flux sorgularını kırar.

## Çalıştırma / geliştirme döngüsü

```powershell
# .env yoksa
Copy-Item .env.example .env  # sonra INFLUX_PASSWORD + INFLUX_TOKEN doldur

docker compose up -d --build      # ilk kurulum / kod değişikliği
docker compose logs -f collector  # canlı log
docker compose restart collector  # yalnızca machines.json değişti
docker compose down               # konteynerleri kapat (volume kalır)
docker compose down -v            # InfluxDB verisini de SİLER (dikkat)
```

InfluxDB UI: <http://localhost:8086> — kimlik bilgileri `.env`'de.

## Ortam notları

- **Docker Desktop yolu**: kullanıcıya özel kurulu. Eğer `docker` PATH'te
  görünmüyorsa şunu komuttan önce ekle:
  `$env:PATH = "$env:LOCALAPPDATA\Programs\DockerDesktop\resources\bin;$env:PATH"`.
- **Shell**: PowerShell 5.1 (Windows). `&&` yok — `;` veya `if ($?) { ... }`
  kullan. Native exe stderr'i `2>&1` ile yönlendirme (`$?` bozulur).
- **gh CLI**: `C:\Program Files\GitHub CLI\gh.exe`. PATH'te değilse
  tam yoldan çağır. Auth: `serkankose77` (gho_ token, repo+gist+read:org).
- **Test çalıştırma**: tezgahlara erişim ofis ağına bağlı; geliştirme
  makinesinden tezgahlar erişilemez olabilir. Bu durumda
  `docker compose up` çalıştırmak yerine collector'ın import + parse
  yolunu yerel `python -m py_compile collector/collector.py` ile veya
  küçük bir XML fixture'la doğrulayın.

## Yazım stili

- **Kullanıcıya cevap dilinizi Türkçe tutun** (kullanıcı Türkçe yazıyor).
  Kod yorumları, log mesajları, commit/PR mesajları İngilizce olabilir.
- README'de Türkçe karakterler kullanılır; collector loglarında ASCII
  tercih edin (Windows konsol kodlama sorunlarını önler).
- Yeni dosya / paket eklerken minimum tut: tek dosyalık collector
  bilinçli bir tercih, çoklu modüle bölmek için somut bir gerekçe olsun.

## Scope koruma

Aşağıdaki işler "ileride" kategorisinde — kullanıcı açıkça istemeden
**eklemeyin**:

- Grafana servis tanımı / pano JSON'ları
- OEE matematiği (Availability × Performance × Quality)
- Vardiya / planlı duruş takvimi
- Kullanıcı arayüzü, REST API, kimlik doğrulama
- Telegraf (collector zaten yazıyor — Telegraf gereksiz katman olur)
- Alarm / Slack / e-posta entegrasyonu

Bu repo veri toplama boru hattıdır. Yeni kapsam isteklerini önce kullanıcıyla
doğrulayın.

## Değişiklik / commit kuralları

- Commit mesajları İngilizce, imperative ("Add X", "Fix Y").
- Co-Authored-By satırı eklemeyin (önceki oturumda hook reddetti).
- `gh` üzerinden PR açmadan önce `git status` + `git diff` + tüm
  dallanma commit'lerini gözden geçirin (sadece son commit değil).
- `.env`, `*.env.local`, `__pycache__/` zaten `.gitignore`'da; yeni
  sırlar/derleme artıkları eklerseniz `.gitignore`'u da güncelleyin.

## Hızlı referanslar

- Repo: <https://github.com/serkankose77/SE-HAVACILIK-OEE>
- MTConnect standardı: <https://www.mtconnect.org/standard>
- InfluxDB 2.7 docs: <https://docs.influxdata.com/influxdb/v2/>
- Haas MTConnect agent: tezgah üzerinde Setting 9000+ ile etkin,
  varsayılan port **8082**. `/current` snapshot, `/sample?from=N` stream.
