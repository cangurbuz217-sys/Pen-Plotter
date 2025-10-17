# Pen Plotter Text-to-G-code

Bu depo, TrueType fontları kullanarak istediğiniz metni 3B yazıcı veya pen plotter cihazlarında kullanılabilecek G-code dosyalarına dönüştüren bir Python aracını içerir. Web tabanlı [3dwriter.io](https://3dwriter.io) uygulamasının sunduğu temel işlevlerin tamamını komut satırı üzerinden sağlar ve istediğiniz `.ttf` yazı tipini kullanmanıza olanak tanır.

## Özellikler

- Yeni **Pen Plotter Studio** masaüstü arayüzü; yatak boyutunu, pen ofsetlerini ve pen yukarı/aşağı yüksekliklerini belirleyip canlı önizleme ile sınırlar içinde çalışmanızı sağlar.
- Her metin bloğunun kendi font boyutu, satır aralığı, harf aralığı ve konumu bulunur; blokları sürükleyip bırakabilir ve aynı projede farklı kombinasyonlar kullanabilirsiniz.
- `.ttf` veya `.otf` fontlarını yükleyerek konturları tek çizgilik merkez hattına dönüştürür; scikit-image tabanlı medial-axis + OpenCV inceltme kombinasyonu sayesinde çizgiler daha düzgün ve kesintisizdir.
- Boşta ve çizim hızlarını mm/s cinsinden girip G-code üretimi sırasında otomatik olarak mm/dakikaya dönüştürür.
- Proje ayarlarını JSON olarak kaydedip daha sonra tekrar yükleyebilir, G-code çıktısını tek tuşla kaydedebilirsiniz.
- Konturlar oluşturulmadan önce tahmini boyut ve çizim uzunluğu için ön izleme sağlar.

## Kurulum

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Kullanım

Temel kullanım şu şekildedir:

```bash
python -m pen_plotter.cli "Merhaba Dünya" --font /path/to/font.ttf --output merhaba.gcode
```

Önemli seçenekler:

- `--font-size`: Yazı yüksekliğini milimetre cinsinden belirtir (varsayılan 12 mm).
- `--line-spacing`: Satırlar arasındaki çarpan (1.3 varsayılan).
- `--char-spacing`: Harfler arasına ekstra boşluk ekler.
- `--curve-tolerance`: Bézier eğrilerinin çizgi segmentlerine çevrilirken izin verilen maksimum sapma (mm).
- `--stroke-mode`: Varsayılan `centerline` değeri tek çizgi vuruşları üretir; gerekirse `outline` seçeneği konturları iki çizgi olarak korur.
- `--center`: Metni koordinat düzleminin merkezine hizalar.
- `--origin-x`, `--origin-y`: Metni belirtilen konuma taşır.
- `--preview`: G-code kaydedilmeden önce boyut ve toplam çizim uzunluğunu yazdırır.

Üretilen G-code dosyasını standart pen plotter veya 3B yazıcı kontrol yazılımlarına aktarabilirsiniz.

## Grafik Arayüz: Pen Plotter Studio

`plotter_gui.py` dosyası, 3dwriter.io'dakine benzer bir arayüz sağlar. Yan tarafta metninizi ve ayarları girer, sağdaki önizleme ızgarasında sonuçları anında görür ve istediğiniz `.ttf` fontu yüklemek için özel bir **Font Aç** butonu kullanırsınız.

### Windows 11 için adım adım kurulum (``C:\Users\cangu\Desktop`` baz alınmıştır)

1. [python.org](https://www.python.org/downloads/windows/) adresinden **Windows (64-bit) için Python 3.11** kurulum paketini indirin.
2. Yükleyiciyi açın, **Add Python to PATH** kutusunu işaretleyin ve kurulumu tamamlayın.
3. `Win` tuşuna basıp **PowerShell** yazın, sağ tıklayıp **Run as administrator** seçmeden normal olarak açın.
4. Aşağıdaki komutla masaüstüne gidin:

   ```powershell
   cd C:\Users\cangu\Desktop
   ```

5. Proje için izole bir ortam oluşturun ve etkinleştirin:

   ```powershell
   python -m venv pen-plotter-gui
   .\pen-plotter-gui\Scripts\Activate.ps1
   ```

6. Gerekli paketleri yükleyin (OpenCV, scikit-image ve bağımlılıkları birkaç dakika sürebilir):

   ```powershell
   pip install -r requirements.txt
   ```

7. Depoyu eksiksiz indirmek için aşağıdaki PowerShell komutunu çalıştırın. Kendi GitHub kullanıcı adınızı ve depo adınızı kullanmayı unutmayın (örnek: `https://codeload.github.com/cangu/Pen-Plotter/zip/refs/heads/main`).

   ```powershell
   Invoke-WebRequest -Uri "https://codeload.github.com/<github-kullanici-adiniz>/Pen-Plotter/zip/refs/heads/main" -OutFile Pen-Plotter.zip
   Expand-Archive Pen-Plotter.zip -DestinationPath . -Force
   Rename-Item Pen-Plotter-main Pen-Plotter -Force
   ```

   Komutlar tamamlandığında masaüstünüzde `Pen-Plotter` adlı klasör oluşur ve içinde `plotter_gui.py`, `requirements.txt` ve `pen_plotter` klasörünü görmelisiniz. Eğer farklı bir klasör adı oluşursa (örneğin `Pen-Plotter-main`), onu sağ tıklayıp **Rename** ile `Pen-Plotter` olarak değiştirin.
8. PowerShell penceresinde projenin içine girin:

   ```powershell
   cd C:\Users\cangu\Desktop\Pen-Plotter
   ```

9. Grafik arayüzü başlatın:

   ```powershell
   python plotter_gui.py
   ```

   İsterseniz aynı klasördeki `plotter_gui.py` dosyasına çift tıklayarak da çalıştırabilirsiniz; program açıldığında kapanmaması için bu komut penceresi açık kalacaktır.

10. Açılan pencerede şu adımları uygulayın:
    - **TTF font seç** butonuna tıklayıp istediğiniz `.ttf` veya `.otf` dosyasını seçin (ör. `C:\Users\cangu\Desktop\Fontlar\el_yazisi.ttf`).
    - Sol paneldeki **Metin bloğu ekle** butonu ile istediğiniz kadar blok oluşturun; her blokta font boyutu, satır aralığı ve harf aralığı farklı olabilir.
    - Sağdaki ızgaradan blokları fareyle sürükleyerek yatak sınırları içinde yerleştirin; önizleme, blok yatak dışına taşarsa kırmızı bir uyarı gösterir.
    - Üst kısımdaki Bed/Pen ayarlarından yatak boyutu, pen offset, pen yukarı/aşağı değerleri ile boşta/çizim hızlarını milimetre/saniye cinsinden girin; pen offset için turuncu kılavuz çizgileri çalışma alanında görüntülenir.
    - Varsayılan merkez hattı (centerline) modu konturları tek vuruşlu çizgilere indirger; gerekirse G-code kaydetmeden önce komut satırı sürümünde `--stroke-mode outline` kullanabilirsiniz.
    - **Projeyi kaydet** diyerek tüm parametreleri `.json` olarak saklayabilir, **Projeyi aç** ile tekrar yükleyebilirsiniz.
    - **G-code kaydet** butonuyla oluşturulan yolları kaydedip cihazınıza aktarabilirsiniz; pen offset değeri otomatik uygulanır.

11. Kaydedilen G-code'u pen plotter veya 3B yazıcı yazılımınıza aktarın.

> **İpucu:** Uygulamada **Metni merkezde hizala** seçeneği işaretliyse önizlemede gördüğünüz hizalama aynen G-code çıktısına da uygulanır. Origin X/Y alanlarını kullanarak çıktıyı çalışma yüzeyinizdeki referans noktasına kaydırabilirsiniz.

## Geliştirme

Modül yapısı:

- `pen_plotter/font_paths.py`: Font konturlarını çoklu çizgi (polyline) yollarına çevirir.
- `pen_plotter/centerline.py`: Kontur dolgusunu inceleyerek tek stroke merkez hatlarını üretir (scikit-image medial axis + OpenCV inceltme) ve yolları düzgün tek çizgilere indirgemek için ek yumuşatma/adımlama uygular.
- `pen_plotter/gcode.py`: Çoklu çizgi yollarını pen plotter dostu G-code komutlarına dönüştürür.
- `pen_plotter/cli.py`: Komut satırı arabirimi.

Yeni özellikler eklerken `fonttools` kütüphanesini kullanan bu akışa uygunluk sağlayın.
