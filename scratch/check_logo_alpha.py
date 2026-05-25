from PIL import Image
img = Image.open(r'C:\Programming\IRLPC Hyperframes\animations\logo-flip\logo-rbypc.png')
print('mode:', img.mode, 'size:', img.size)
print('corner pixels:', img.getpixel((0, 0)), img.getpixel((3839, 0)),
      img.getpixel((0, 2159)), img.getpixel((3839, 2159)))
print('center pixel:', img.getpixel((1920, 1080)))
alpha = img.split()[3]
print('alpha min/max:', alpha.getextrema())
hist = alpha.histogram()
print(f'fully opaque(255): {hist[255]}, fully transparent(0): {hist[0]}, partial: {sum(hist[1:255])}')
