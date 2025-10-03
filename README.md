# Pen Plotter Text-to-G-code

Bu depo, TrueType fontları kullanarak istediğiniz metni 3B yazıcı veya pen plotter cihazlarında kullanılabilecek G-code dosyalarına dönüştüren bir Python aracını içerir. Web tabanlı [3dwriter.io](https://3dwriter.io) uygulamasının sunduğu temel işlevlerin tamamını komut satırı üzerinden sağlar ve istediğiniz `.ttf` yazı tipini kullanmanıza olanak tanır.

## Özellikler

- Yeni **Pen Plotter Studio** masaüstü arayüzü; yazınızı küçük bir koordinat sisteminde anında önizleme imkânı sunar.
- Herhangi bir TTF fontundan bezier konturlarını çizgi segmentlerine dönüştürür.
- Metni satırlara böler, satır ve karakter aralıklarını ayarlamanıza izin verir.
- Çıkışı belirlediğiniz koordinatlara taşır veya otomatik olarak merkezler.
- Seyahat/drawing hızları ve pen yüksekliği dahil olmak üzere G-code parametrelerini özelleştirin.
- Konturlar oluşturulmadan önce tahmini boyut ve çizim uzunluğu için ön izleme.

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

6. Gerekli paketi yükleyin:

   ```powershell
   pip install fonttools
   ```

7. Bu depoyu GitHub'dan **Code → Download ZIP** seçeneğiyle indirip `C:\Users\cangu\Desktop` içine çıkarın. Çıkan klasörün adını örneğin `Pen-Plotter` olarak bırakabilirsiniz.
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
    - **Font Aç** butonuna tıklayıp istediğiniz `.ttf` veya `.otf` dosyasını seçin (ör. `C:\Users\cangu\Desktop\Fontlar\el_yazisi.ttf`).
    - Sol kutuya yazmak istediğiniz metni girin; sağdaki kare ızgarada önizleme hemen güncellenecektir.
    - Gerekirse font boyutu, satır aralığı, harf aralığı ve eğri toleransı değerlerini değiştirin.
    - Seyahat/drawing hızları ve Z yüksekliği gibi G-code parametrelerini alt bölümden düzenleyin.
    - **G-code Kaydet** butonuna bastığınızda, varsayılan olarak masaüstünüze kaydedilecek `.gcode` dosyasının adını belirleyin.

11. Kaydedilen G-code'u pen plotter veya 3B yazıcı yazılımınıza aktarın.

> **İpucu:** Uygulamada **Metni merkezde hizala** seçeneği işaretliyse önizlemede gördüğünüz hizalama aynen G-code çıktısına da uygulanır. Origin X/Y alanlarını kullanarak çıktıyı çalışma yüzeyinizdeki referans noktasına kaydırabilirsiniz.

## Tek Dosyalık Kullanım (Kopyala & Çalıştır)

Komut satırı ve depo yapısıyla uğraşmak istemiyorsanız `single_file_plotter.py`
dosyasını açıp içeriğini olduğu gibi kopyalayabilirsiniz. Ardından şu adımları
izleyin:

1. Bilgisayarınızda Python 3 kurulu olduğundan emin olun.
2. Boş bir klasör oluşturun ve içerisine yeni bir metin dosyası açıp
   `plotter.py` adıyla kaydedin.
3. Bu depodaki `single_file_plotter.py` dosyasının tamamını kopyalayıp
   `plotter.py` dosyasına yapıştırın.
4. Terminali/komut istemcisini açıp dosyanın olduğu klasöre gelin.
5. Gerekli tek kütüphaneyi kurun:

   ```bash
   pip install fonttools
   ```

6. Kendi metninizi ve font yolunuzu kullanarak G-code üretin:

   ```bash
   python plotter.py --text "Merhaba" --font "C:/Fonts/BenimFontum.ttf" --output merhaba.gcode --preview --center
   ```

Komut sonrasında `merhaba.gcode` dosyası aynı klasörde oluşur. Farklı ayarlar
için `python plotter.py --help` komutunu çalıştırabilirsiniz.

## Geliştirme

Modül yapısı:

- `pen_plotter/font_paths.py`: Font konturlarını çoklu çizgi (polyline) yollarına çevirir.
- `pen_plotter/gcode.py`: Çoklu çizgi yollarını pen plotter dostu G-code komutlarına dönüştürür.
- `pen_plotter/cli.py`: Komut satırı arabirimi.

Yeni özellikler eklerken `fonttools` kütüphanesini kullanan bu akışa uygunluk sağlayın.
