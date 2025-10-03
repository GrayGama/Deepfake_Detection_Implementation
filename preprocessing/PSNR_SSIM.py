import cv2
import numpy as np
from skimage.metrics import structural_similarity as ssim

def calculate_psnr(original, compressed):
    mse = np.mean((original - compressed) ** 2)
    if mse == 0:
        return 100
    max_pixel = 255.0
    psnr = 20 * np.log10(max_pixel / np.sqrt(mse))
    return psnr

def calculate_ssim(original, compressed):
    return ssim(original, compressed, data_range=compressed.max() - compressed.min(), multichannel=True)

# Load images
original = cv2.imread('./datasets/FaceForensics++/manipulated_sequences/Face2Face/c23/frames/000_003/000.png')
# compressed = cv2.imread('./datasets/FaceForensics++/manipulated_sequences/Deepfakes/c40/frames/000_003/000.png')
compressed = cv2.imread('./datasets/ff++_compressed/manipulated_sequences/Face2Face/c85/frames/000_003/000.jpg')

# Convert images to grayscale for SSIM
original_gray = cv2.cvtColor(original, cv2.COLOR_BGR2GRAY)
compressed_gray = cv2.cvtColor(compressed, cv2.COLOR_BGR2GRAY)

# Calculate metrics
psnr_value = calculate_psnr(original_gray, compressed_gray)
ssim_value = calculate_ssim(original_gray, compressed_gray)

print(f"PSNR: {psnr_value}")
print(f"SSIM: {ssim_value}")