# SE Havacılık OEE — Claude project guide

Bu dosya bu repoda çalışan Claude Code oturumları için kalıcı bağlamdır.
Lütfen yeni bir oturum açtığında önce buradaki kuralları yükle, sonra
göreve başla.

## Bağlam

- **Sahip / kullanıcı**: Serkan Köse (`serkankose77`), SE Havacılık.
- **Amaç**: 5 adet Haas CNC tezgahından MTConnect (port 8082) ile veri
  toplayıp InfluxDB 2.7'ye yazmak ve Grafana ile günlük/haftalık/aylık
  state (active/running/stopped/offline) yüzdelerini + program çalışma
  süresi ve parça sayısını raporlamak.
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
| `docker-compose.yml`            | InfluxDB + collector + grafana. Healthcheck + bağımlılık zinciri.|
| `.env.example`                  | Şablon. `.env` `.gitignore`'da; **asla commitlenmez**.          |
| `README.md`                     | Türkçe son kullanıcı dokümanı, Flux örnekleri.                  |
| `grafana/provisioning/`         | Datasource + dashboard provider tanımları (kod-olarak yapılandırma). |
| `grafana/dashboards/*.json`     | Dashboard JSON'ları. Düzenle → `restart grafana` (provisioning yeniden yükler). |

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

## Scope

Şu an proje **iki katmandan** oluşuyor:

1. **Veri toplama** (collector → InfluxDB) — birinci faz, tamam.
2. **Görselleştirme** (Grafana → InfluxDB) — kullanıcı 2026-05-08'de
   istedi; aktif geliştirme. State haritalaması, dashboard JSON'ları,
   provisioning dosyaları artık scope içinde.

### State haritalaması (üzerinde anlaşılan)

Grafana sorguları aşağıdaki dört state'i bekler. **Etiketler 2026-05-08
sonu kullanıcı isteğiyle yeniden adlandırıldı** — eski `ACTIVE` artık
`RUNNING`, eski `RUNNING` (idle) artık `IDLE`:

| Etiket    | Koşul                                                              | MTConnect karşılığı (sorgularda kalır) |
| --------- | ------------------------------------------------------------------ | -------------------------------------- |
| `OFFLINE` | `mtconnect_status.reachable=false`                                 | —                                      |
| `STOPPED` | `Execution=UNAVAILABLE`                                            | `r._value == "UNAVAILABLE"`            |
| `IDLE`    | `Execution IN (READY, STOPPED, INTERRUPTED, FEED_HOLD)`            | else dalı                              |
| `RUNNING` | `Execution=ACTIVE` (program in-cycle, takım işliyor)               | `r._value == "ACTIVE"`                 |

> Flux sorgularında `r._value == "ACTIVE"` MTConnect ham veri değeridir
> ve **DEĞİŞMEZ**. Yalnızca dashboard çıktı etiketleri (state kolon adı,
> mappings, override matchers) `RUNNING` / `IDLE` adlarını kullanır.

Süre hesabı için **count × POLL_INTERVAL** yaklaşımı kullanılır
(2 sn polling, ±2 sn hata payı). İleride istenirse `stateDuration()`
ile time-weighted hesaba geçilebilir.

### Hâlâ scope dışı (kullanıcı açıkça istemedikçe eklemeyin)

- OEE matematiğinin tam halinin (Availability × Performance × Quality)
  formülize edilmiş şekilde yazımı — yalnızca state yüzdeleri + program
  süresi + parça sayısı raporlanıyor şu an.
- Vardiya / planlı duruş takvimi (raw Availability hesaplanıyor).
- REST API, custom UI, kimlik doğrulama (Grafana hariç).
- Telegraf (collector zaten yazıyor — Telegraf gereksiz katman olur).
- Alarm / Slack / e-posta entegrasyonu.

Yeni kapsam isteklerini önce kullanıcıyla doğrulayın.

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
