# Pen Plotter Text-to-G-code

Bu depo, TrueType fontları kullanarak istediğiniz metni 3B yazıcı veya pen plotter cihazlarında kullanılabilecek G-code dosyalarına dönüştüren bir Python aracını içerir. Web tabanlı [3dwriter.io](https://3dwriter.io) uygulamasının sunduğu temel işlevlerin tamamını komut satırı üzerinden sağlar ve istediğiniz `.ttf` yazı tipini kullanmanıza olanak tanır.

## Özellikler

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
