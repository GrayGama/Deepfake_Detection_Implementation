import subprocess
import os
import logging
from tqdm import tqdm

# from PIL import Image

def compress_images(input_folder, output_root, quality):
    all_files = []
    for root, dirs, files in os.walk(input_folder):
        for file in files:
            if file.endswith(".png"):
                all_files.append((root, file))

    for root, file in tqdm(all_files, desc="Compressing images", unit="file"):
        input_path = os.path.join(root, file)
        relative_path = os.path.relpath(root, input_folder)  # Get relative path to maintain structure
        output_folder = os.path.join(output_root, relative_path)
        if not os.path.exists(output_folder):
            os.makedirs(output_folder)
        output_path = os.path.join(output_folder, file.replace('.png', '.jpg'))
        
        # # Skip processing if the output file already exists
        # if os.path.exists(output_path):
        #     logging.info(f"Skipping {output_path} as it already exists.")
        #     continue
        
        # Command to compress images using mozjpeg
        command = [
            'cjpeg',
            '-quality', str(quality),
            '-outfile', output_path, input_path
        ]
        try:
            subprocess.run(command, check=True)
            logging.info(f"Compressed {input_path} to {output_path}")
        except subprocess.CalledProcessError as e:
            logging.error(f"Error processing {input_path}: {e}")
                    
                
if __name__ == '__main__':
     
    input_folder = './datasets/FaceForensics++/original_sequences/youtube/c23/frames'
    output_root = './datasets/FaceForensics++_JPG/manipulated_sequences/Deepfakes/c23/frames'
    # Adjust the quality according to the compression desired (1-100, where 100 means full quality)
    # quality_level = 15
    # quality_level = 10
    quality_level = 100
    compress_images(input_folder, output_root, quality_level)

