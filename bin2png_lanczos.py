#!/usr/bin/env python3

import argparse
import io
import math
import os
import sys
import cv2
import numpy as np

from tempfile import NamedTemporaryFile

from PIL import Image


class FileReader(object):
    def __init__(self, path_or_stream, file_backed=False):
        self.tmpfile = None
        if hasattr(path_or_stream, "name") and path_or_stream.name != "<stdin>":
            self.length = os.path.getsize(path_or_stream.name)
            self.file = path_or_stream
            self.name = path_or_stream.name
        else:
            if sys.version_info.major >= 3:
                file_mode = 'wb'
                read_mode = 'rb'
            else:
                file_mode = 'w'
                read_mode = 'r'
            if isinstance(path_or_stream, str) and path_or_stream != "-":
                with open(path_or_stream, read_mode) as f:
                    infile = f.read()
            elif sys.version_info.major >= 3:
                infile = sys.stdin.buffer.read()
            else:
                infile = sys.stdin.read()
            self.length = len(infile)
            if file_backed:
                tmp = NamedTemporaryFile(delete=False, mode=file_mode)
                self.tmpfile = tmp.name
                tmp.write(infile)
                tmp.close()
                self.file = open(self.tmpfile, read_mode)
                self.name = self.tmpfile
            else:
                self.file = io.BytesIO(infile)
                self.name = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.tmpfile is not None:
            self.file.close()
            os.unlink(self.tmpfile)
            self.tmpfile = None
            self.file = None

    @staticmethod
    def new(path_or_stream, file_backed=False):
        if isinstance(path_or_stream, FileReader):
            return path_or_stream
        else:
            return FileReader(path_or_stream, file_backed=file_backed)

    def __len__(self):
        return self.length

    def read(self, n):
        if sys.version_info.major >= 3:
            return [i for i in self.file.read(n)]
        else:
            return map(ord, self.file.read(n))


def choose_file_dimensions(infile, input_dimensions=None, square=False, verbose=False):
    if input_dimensions is not None and len(input_dimensions) >= 2 and input_dimensions[0] is not None \
            and input_dimensions[1] is not None:
        # the dimensions were already fully specified
        return input_dimensions
    infile = FileReader.new(infile)
    num_bytes = len(infile)
    num_pixels = int(math.ceil(float(num_bytes) / 3.0))
    sqrt = math.sqrt(num_pixels)
    sqrt_max = int(math.ceil(sqrt))

    if square is True:
        return sqrt_max, sqrt_max

    if input_dimensions is not None and len(input_dimensions) >= 1:
        if input_dimensions[0] is not None:
            # the width is specified but the height is not
            if num_pixels % input_dimensions[0] == 0:
                return input_dimensions[0], num_pixels // input_dimensions[0]
            else:
                return input_dimensions[0], num_pixels // input_dimensions[0] + 1
        else:
            # the height is specified but the width is not
            if num_pixels % input_dimensions[1] == 0:
                return num_pixels // input_dimensions[1], input_dimensions[1]
            else:
                return num_pixels // input_dimensions[1] + 1, input_dimensions[1]

    best_dimensions = None
    best_extra_bytes = None
    for i in range(int(sqrt_max), 0, -1):
        is_perfect = num_pixels % i == 0
        if is_perfect:
            dimensions = (i, num_pixels // i)
        else:
            dimensions = (i, num_pixels // i + 1)
        extra_bytes = dimensions[0] * dimensions[1] * 3 - num_bytes
        if dimensions[0] * dimensions[1] >= num_pixels and (best_dimensions is None or extra_bytes < best_extra_bytes):
            best_dimensions = dimensions
            best_extra_bytes = extra_bytes
        if is_perfect:
            break
    if best_extra_bytes > 0:
        if verbose is True:
            sys.stderr.write("Could not find PNG dimensions that perfectly encode "
                             "%s bytes; the encoding will be tail-padded with %s zeros.\n"
                             % (num_bytes, int(best_extra_bytes)))
    return best_dimensions


def file_to_png(infile, outfile, dimensions=None, square=False, verbose=False, no_progress=False, use_lanczos=False):
    reader = FileReader.new(infile)
    dimensions = choose_file_dimensions(reader, dimensions, square=square, verbose=verbose)
    dim = (int(dimensions[0]), int(dimensions[1]))
    img = Image.new('RGB', dim)
    pixels = img.load()
    row = 0
    column = -1
    while True:
        b = reader.read(3)
        if not b:
            break

        column += 1
        if column >= img.size[0]:
            column = 0
            row += 1
            if no_progress is False:
                percent = float(((row + 1) / dimensions[1]) * 100)
                sys.stderr.write("\r%s%s" % (round(percent, 2), "%"))

            if row >= img.size[1]:
                raise Exception("Error: row %s is greater than maximum rows in image, %s." % (row, img.size[1]))

        color = [b[0], 0, 0]
        if len(b) > 1:
            color[1] = b[1]
        if len(b) > 2:
            color[2] = b[2]

        if not row >= img.size[1]:
            pixels[column, row] = tuple(color)
    if no_progress is False:
        sys.stderr.write("\n")

    if sys.version_info.major >= 3 and outfile.name == '<stdout>' and hasattr(outfile, 'buffer'):
        outfile = outfile.buffer
    img.save(outfile, format="PNG")

    ######################## Lanczos addition ########################    
    if use_lanczos:
        # Convert PIL Image to OpenCV format
        img_array = np.array(img)
        img_opencv = cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR)
        target_size = (300, 300)
    
        # Resize using Lanczos
        resized_img = cv2.resize(img_opencv, target_size, interpolation=cv2.INTER_LANCZOS4)
        
        # Convert back to RGB for PIL pipeline
        resized_img_rgb = cv2.cvtColor(resized_img, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(resized_img_rgb)
    ################################################################    

def png_to_file(infile, outfile, no_progress=False, verbose=False):
    with FileReader.new(infile, file_backed=True) as reader:
        img = Image.open(reader.name)
        rgb_im = img.convert('RGB')

        pix_buffer = 0
        for row in range(img.size[1]):
            if not no_progress:
                percent = float(((row + 1) / img.size[1]) * 100)
                sys.stderr.write("\r%s%s" % (round(percent, 2), "%"))
            for col in range(img.size[0]):
                pixel = rgb_im.getpixel((col, row))

                # Omit the null bytes created in the generation of the image file.
                # If it is a null byte, save it for later and see if there is going to be another null byte.
                # If the original file ended in null bytes, it will omit those too, but there is
                # probably no way to detect that.
                for segment in pixel:
                    if segment == 0:
                        pix_buffer += 1
                    else:
                        if pix_buffer != 0:
                            for color in range(pix_buffer):
                                # flush the cache to the file if a non-null byte was detected
                                if sys.version_info.major >= 3:
                                    outfile.write(bytes([0]))
                                else:
                                    outfile.write(chr(0))
                            pix_buffer = 0
                        if sys.version_info.major >= 3:
                            outfile.write(bytes([segment]))
                        else:
                            outfile.write(chr(segment))

        if not no_progress:
            sys.stderr.write("\n")
        if pix_buffer != 0 and verbose:
            length = pix_buffer
            if length == 1:
                sys.stderr.write("Omitting %s zero from end of file\n" % pix_buffer)
            else:  # Why not...
                sys.stderr.write("Omitting %s zeroes from end of file\n" % pix_buffer)


def main(argv=None):
    parser = argparse.ArgumentParser(description="A simple cross-platform script for encoding any binary file into a "
                                                 "lossless PNG.", prog="bin2png")

    if sys.version_info.major >= 3:
        write_mode = 'wb'
        out_default = sys.stdout.buffer
    else:
        write_mode = 'w'
        out_default = sys.stdout
    parser.add_argument('file', nargs="?", default='-', type=str,
                        help="the file to encode as a PNG (defaults to '-', which is stdin)")
    parser.add_argument("-o", "--outfile", type=argparse.FileType(write_mode), default=out_default,
                        help="the output file (defaults to '-', which is stdout)")
    parser.add_argument("-d", "--decode", action="store_true",
                        help="decodes the input PNG back to a file")
    parser.add_argument("-w", "--width", type=int, default=None,
                        help="constrain the output PNG to a specific width")
    parser.add_argument("-l", "--height", type=int, default=None,
                        help="constrain the output PNG to a specific height")
    parser.add_argument("-s", "--square", action="store_true", help="generate only square images")
    parser.add_argument("-v", "--verbose", action="store_true", help="enable debugging messages")
    parser.add_argument("--no-progress", action="store_true", help="don't display percent progress")
    parser.add_argument("--use-lanczos", action="store_true", help="use Lanczos interpolation and resize the image to 300x300")

    if argv is None:
        argv = sys.argv[1:]

    args = parser.parse_args(argv)

    if args.decode:
        png_to_file(args.file, args.outfile, no_progress=args.no_progress, verbose=args.verbose)
    else:
        dims = None
        if args.height is not None or args.width is not None:
            dims = (args.width, args.height)

        file_to_png(args.file, args.outfile, dimensions=dims, square=args.square, verbose=args.verbose,
                   no_progress=args.no_progress, use_lanczos=args.use_lanczos)


if __name__ == "__main__":
    main()
