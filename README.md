# SE Havacılık OEE

Haas CNC tezgahlarından **MTConnect** üzerinden veri toplayıp **InfluxDB**'ye
yazan Docker tabanlı boru hattı. İlk faz: yalnızca veri toplama ve zaman
serisi veritabanına yazma. Arayüz / Grafana / OEE hesabı sonraki fazlarda
eklenecek.

## Mimari

```
┌──────────────────────┐   HTTP/XML (MTConnect)   ┌──────────────────┐   Line Protocol   ┌──────────────┐
│ Haas Tezgahları      │ ───────────────────────► │ collector (Py)   │ ────────────────► │ InfluxDB 2.x │
│ (5 adet, port 8082)  │   /current  her ~2 sn    │  Docker konteyner│                   │  Docker      │
└──────────────────────┘                          └──────────────────┘                   └──────────────┘
```

- **collector**: `machines.json` listesindeki her tezgahın
  `http://<host>:8082/current` MTConnect endpoint'ini periyodik olarak
  çeker, XML'i ayrıştırır ve InfluxDB'ye yazar.
- **influxdb**: InfluxDB 2.7. UI: `http://localhost:8086`.
- Her ikisi de `docker-compose` ile birlikte çalışır.

## Tezgahlar (`machines.json`)

| ID      | Ad        | Model                       | IP             |
| ------- | --------- | --------------------------- | -------------- |
| vf6     | VF-6/40   | Haas VF-6/40 · 3-axis mill  | 192.168.1.113  |
| vf4     | VF-4      | Haas VF-4 · 3-axis mill     | 192.168.1.115  |
| umc400  | UMC-400   | Haas UMC-400 · 5-axis mill  | 192.168.1.114  |
| umc750  | UMC-750   | Haas UMC-750 · 5-axis mill  | 192.168.1.116  |
| st10    | ST-10     | Haas ST-10 · Lathe          | 192.168.1.112  |

Tüm tezgahların MTConnect agent'ı port **8082** üzerinden hizmet veriyor.

## Hızlı başlangıç

> Gereksinim: Docker Desktop. Tezgahların IP'lerine ulaşılabilen bir
> ağda olmalısınız (192.168.1.0/24).

```powershell
# 1) Reposu klonla
git clone https://github.com/serkankose77/SE-HAVACILIK-OEE.git
cd SE-HAVACILIK-OEE

# 2) Ortam değişkenlerini hazırla
Copy-Item .env.example .env
# .env dosyasını açıp INFLUX_PASSWORD ve INFLUX_TOKEN değerlerini doldur

# 3) Ayağa kaldır
docker compose up -d --build

# 4) Logları izle
docker compose logs -f collector
```

InfluxDB UI: <http://localhost:8086>
- Kullanıcı: `.env` içindeki `INFLUX_USERNAME`
- Şifre: `.env` içindeki `INFLUX_PASSWORD`
- Org: `se-havacilik` (varsayılan)
- Bucket: `mtconnect` (varsayılan)

## Toplanan veri

Collector her bir MTConnect DataItem'ı ayrı bir nokta olarak yazar.

**Measurement**: `mtconnect`

**Tag'ler**:
- `machine_id` — `vf6`, `vf4`, `umc400`, `umc750`, `st10`
- `machine_name` — `VF-6/40`, `VF-4`, ...
- `machine_type` — `mill` veya `lathe`
- `category` — `Events`, `Samples`, `Condition`
- `item_type` — XML eleman adı (`Availability`, `Execution`, `PathFeedrate`, ...)
- `name` — DataItem adı (`avail`, `execution`, `Frt`, `Sload`, `PartCount`, ...)
- `component` — Bileşen adı (`Controller`, `Path`, `Axes`, ...)
- `sub_type` — `ACTUAL`, `COMMANDED`, `OVERRIDE`, ... (varsa)
- `condition_type` — `SYSTEM`, `LOGIC_PROGRAM`, ... (yalnızca Condition)

**Field'lar**:
- `value` (float) — Sayısal Sample değerleri (feedrate, spindle load, eksen
  pozisyonu, vb.)
- `value_str` (string) — Event/Condition değerleri (`AUTOMATIC`, `ACTIVE`,
  `AVAILABLE`, ...) ve `UNAVAILABLE` durumundaki Sample değerleri
- `state` (string) — Condition için kondisyon durumu
  (`Normal` / `Warning` / `Fault` / `Unavailable`)

Ek olarak `mtconnect_status` measurement'ı her döngüde tezgahın HTTP
ulaşılabilirliğini (`reachable=true|false`) yazar; bunu Availability
hesaplarken kullanabilirsiniz.

## Örnek Flux sorguları

**Son durumdaki Execution değerleri:**
```flux
from(bucket: "mtconnect")
  |> range(start: -5m)
  |> filter(fn: (r) => r._measurement == "mtconnect")
  |> filter(fn: (r) => r.name == "execution")
  |> filter(fn: (r) => r._field == "value_str")
  |> last()
```

**Spindle load zaman serisi (UMC-750):**
```flux
from(bucket: "mtconnect")
  |> range(start: -1h)
  |> filter(fn: (r) => r._measurement == "mtconnect")
  |> filter(fn: (r) => r.machine_id == "umc750")
  |> filter(fn: (r) => r.name == "Sload" and r._field == "value")
```

**Tezgah çevrimiçi kalma oranı (son 24 saat):**
```flux
from(bucket: "mtconnect")
  |> range(start: -24h)
  |> filter(fn: (r) => r._measurement == "mtconnect_status")
  |> filter(fn: (r) => r._field == "reachable")
  |> mean()
  |> group(columns: ["machine_id"])
```

## Yapılandırma (`.env`)

| Değişken           | Açıklama                                      | Varsayılan        |
| ------------------ | --------------------------------------------- | ----------------- |
| `INFLUX_USERNAME`  | İlk kurulumda oluşturulan admin kullanıcı     | `admin`           |
| `INFLUX_PASSWORD`  | Admin şifresi (zorunlu, güçlü olsun)          | —                 |
| `INFLUX_ORG`       | InfluxDB organization adı                     | `se-havacilik`    |
| `INFLUX_BUCKET`    | Veri yazılacak bucket                         | `mtconnect`       |
| `INFLUX_TOKEN`     | Admin token (zorunlu, uzun rastgele dize)     | —                 |
| `INFLUX_RETENTION` | Bucket retention (saniye, 0 = sonsuz)         | `0`               |
| `INFLUX_PORT`      | Host'ta açılacak port                         | `8086`            |
| `POLL_INTERVAL`    | Her tezgahın saniyede bir kez sorgulanması    | `2`               |
| `HTTP_TIMEOUT`     | MTConnect HTTP zaman aşımı (sn)               | `5`               |
| `LOG_LEVEL`        | `DEBUG` / `INFO` / `WARNING`                  | `INFO`            |

## Tezgah listesini düzenlemek

`machines.json` dosyasını düzenleyip `docker compose restart collector`
ile değişikliği uygula. Format:

```json
{
  "<id>": {
    "name":  "<insan-okur-isim>",
    "model": "<model-aciklamasi>",
    "host":  "<ip-veya-hostname>",
    "port":  8082,
    "type":  "mill | lathe"
  }
}
```

## Sorun giderme

**Collector "fetch ... failed" yazıyor.** Tezgah ağı erişilemez ya da
MTConnect agent çalışmıyor olabilir. Test edin:
```powershell
curl http://192.168.1.113:8082/current
```

**InfluxDB sağlıksız (unhealthy).** İlk kurulum tamamlanmamış olabilir.
`docker compose logs influxdb` çıktısına bakın. Sıfırdan başlamak için:
```powershell
docker compose down -v
docker compose up -d
```
> Uyarı: `-v` bayrağı tüm InfluxDB verisini siler.

**Token geçersiz.** `.env` içindeki `INFLUX_TOKEN` ile bucket'a erişen
collector aynı token'ı kullanır. Token'ı değiştirmek için bucket'ı
sıfırlamanız gerekir (`down -v`) veya Influx UI'dan yeni bir token
oluşturup `.env` ve `docker compose restart collector` yapın.

## Yol haritası

- [x] MTConnect → InfluxDB veri toplama
- [ ] Grafana panosu (OEE, Availability, Performance, Quality)
- [ ] Vardiya / planlı duruş takvimi entegrasyonu
- [ ] Üretim sayacı (PartCount) bazlı OEE hesabı
- [ ] Alarm / bildirim entegrasyonu

## Lisans

İç kullanım — SE Havacılık.
