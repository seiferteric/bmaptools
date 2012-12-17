""" This test verifies the base bmap creation and copying API functionality. It
generates a random sparse file, then creates a bmap fir this file and copies it
to a different file using the bmap. Then it compares the original random sparse
file and the copy and verifies that they are identical. """

# Disable the following pylint recommendations:
#   *  Too many public methods - R0904
# pylint: disable=R0904

import os
import sys
import tempfile
import filecmp
import hashlib
import unittest
import itertools
import random

import tests.helpers
from bmaptools import BmapCreate, BmapCopy, Fiemap, TransRead

class Error(Exception):
    """ A class for exceptions generated by this test. """
    pass

def _compare_holes(file1, file2):
    """ Make sure that files 'file1' and 'file2' have holes at the same places.
    The 'file1' and 'file2' arguments may be full file paths or file
    objects. """

    fiemap1 = Fiemap.Fiemap(file1)
    fiemap2 = Fiemap.Fiemap(file2)

    iterator1 = fiemap1.get_unmapped_ranges(0, fiemap1.blocks_cnt)
    iterator2 = fiemap2.get_unmapped_ranges(0, fiemap2.blocks_cnt)

    iterator = itertools.izip_longest(iterator1, iterator2)
    for range1, range2 in iterator:
        if range1 != range2:
            raise Error("mismatch for hole %d-%d, it is %d-%d in file2" \
                        % (range1[0], range1[1], range2[0], range2[1]))

def _generate_compressed_files(file_obj, delete = True):
    """ This is a generator which yields compressed versions of a file
    represented by a file object 'file_obj'.

    The 'delete' argument specifies whether the compressed files that this
    generator yields have to be automatically deleted. """

    import bz2
    import gzip
    import tarfile
    import shutil

    # Make sure the temporary files start with the same name as 'file_obj' in
    # order to simplify debugging.
    prefix = os.path.splitext(os.path.basename(file_obj.name))[0] + '.'
    # Put the temporary files in the directory with 'file_obj'
    directory = os.path.dirname(file_obj.name)

    # Generate an uncompressed version of the file
    tmp_file_obj = tempfile.NamedTemporaryFile('wb+', prefix = prefix,
                                               delete = delete, dir = directory,
                                               suffix = '.uncompressed')
    file_obj.seek(0)
    shutil.copyfileobj(file_obj, tmp_file_obj)
    tmp_file_obj.flush()
    yield tmp_file_obj.name
    tmp_file_obj.close()

    # Generate a .bz2 version of the file
    tmp_file_obj = tempfile.NamedTemporaryFile('wb+', prefix = prefix,
                                               delete = delete, dir = directory,
                                               suffix = '.bz2')
    bz2_file_obj = bz2.BZ2File(tmp_file_obj.name, 'wb')
    file_obj.seek(0)
    shutil.copyfileobj(file_obj, bz2_file_obj)
    bz2_file_obj.close()
    yield bz2_file_obj.name
    tmp_file_obj.close()

    # Generate a .gz version of the file
    tmp_file_obj = tempfile.NamedTemporaryFile('wb+', prefix = prefix,
                                               delete = delete, dir = directory,
                                               suffix = '.gz')
    gzip_file_obj = gzip.GzipFile(tmp_file_obj.name, 'wb')
    file_obj.seek(0)
    shutil.copyfileobj(file_obj, gzip_file_obj)
    gzip_file_obj.close()
    yield gzip_file_obj.name
    tmp_file_obj.close()

    # Generate a tar.gz version of the file
    tmp_file_obj = tempfile.NamedTemporaryFile('wb+', prefix = prefix,
                                               delete = delete, dir = directory,
                                               suffix = '.tar.gz')
    tgz_file_obj = tarfile.open(tmp_file_obj.name, "w:gz")
    tgz_file_obj.add(file_obj.name)
    tgz_file_obj.close()
    yield tgz_file_obj.name
    tmp_file_obj.close()

    # Generate a tar.bz2 version of the file
    tmp_file_obj = tempfile.NamedTemporaryFile('wb+', prefix = prefix,
                                               delete = delete, dir = directory,
                                               suffix = '.tar.bz2')
    tbz2_file_obj = tarfile.open(tmp_file_obj.name, "w:bz2")
    tbz2_file_obj.add(file_obj.name)
    tbz2_file_obj.close()
    yield tbz2_file_obj.name
    tmp_file_obj.close()

def _calculate_sha1(file_obj):
    """ Calculates SHA1 checksum for the contents of file object
    'file_obj'.  """

    file_obj.seek(0)
    hash_obj = hashlib.new("sha1")

    chunk_size = 1024*1024

    while True:
        chunk = file_obj.read(chunk_size)
        if not chunk:
            break
        hash_obj.update(chunk)

    return hash_obj.hexdigest()

def _copy_image(image, f_dest, f_bmap, image_sha1, image_size):
    """ Copy image 'image' using bmap 'f_bmap' to the destination file
    'f_dest'. """

    if hasattr(image, "read"):
        f_image = image
        image.seek(0)
    else:
        f_image = TransRead.TransRead(image)

    f_dest.seek(0)
    if f_bmap:
        f_bmap.seek(0)

    writer = BmapCopy.BmapCopy(f_image, f_dest, f_bmap, image_size)
    # Randomly decide whether we want the progress bar or not
    if bool(random.getrandbits(1)):
        writer.set_progress_indicator(sys.stdout, None)
    writer.copy(bool(random.getrandbits(1)), bool(random.getrandbits(1)))

    # Compare the original file and the copy are identical
    f_dest.seek(0)
    assert _calculate_sha1(f_dest) == image_sha1

    if not hasattr(image, "read"):
        f_image.close()

def _do_test(f_image, image_size, delete = True):
    """" A basic test for the bmap creation and copying functionality. It first
    generates a bmap for file object 'f_image', and then copies the sparse file
    to a different file, and then checks that the original file and the copy
    are identical.

    The 'image_size' argument is size of the image in bytes. The 'delete'
    argument specifies whether the temporary files that this function creates
    have to be automatically deleted. """

    # Make sure the temporary files start with the same name as 'f_image' in
    # order to simplify debugging.
    prefix = os.path.splitext(os.path.basename(f_image.name))[0] + '.'
    # Put the temporary files in the directory with the image
    directory = os.path.dirname(f_image.name)

    # Create and open a temporary file for a copy of the copy
    f_copy = tempfile.NamedTemporaryFile("wb+", prefix = prefix,
                                        delete = delete, dir = directory,
                                        suffix = ".copy")

    # Create and open 2 temporary files for the bmap
    f_bmap1 = tempfile.NamedTemporaryFile("w+", prefix = prefix,
                                          delete = delete, dir = directory,
                                          suffix = ".bmap1")
    f_bmap2 = tempfile.NamedTemporaryFile("w+", prefix = prefix,
                                          delete = delete, dir = directory,
                                          suffix = ".bmap2")

    image_sha1 = _calculate_sha1(f_image)

    #
    # Pass 1: generate the bmap, copy and compare
    #

    # Create bmap for the random sparse file
    creator = BmapCreate.BmapCreate(f_image.name, f_bmap1.name)
    creator.generate()

    _copy_image(f_image, f_copy, f_bmap1, image_sha1, image_size)

    # Make sure that holes in the copy are identical to holes in the random
    # sparse file.
    _compare_holes(f_image.name, f_copy.name)

    #
    # Pass 2: same as pass 1, but use file objects instead of paths
    #

    creator = BmapCreate.BmapCreate(f_image, f_bmap2)
    creator.generate()
    _copy_image(f_image, f_copy, f_bmap2, image_sha1, image_size)
    _compare_holes(f_image, f_copy)

    # Make sure the bmap files generated at pass 1 and pass 2 are identical
    assert filecmp.cmp(f_bmap1.name, f_bmap2.name, False)

    #
    # Pass 3: test compressed files copying with bmap
    #

    for compressed in _generate_compressed_files(f_image, delete = delete):
        _copy_image(compressed, f_copy, f_bmap1, image_sha1, image_size)

        # Test without setting the size
        _copy_image(compressed, f_copy, f_bmap1, image_sha1, None)

        # Append a "file:" prefixe to make BmapCopy use urllib
        compressed = "file:" + compressed
        _copy_image(compressed, f_copy, f_bmap1, image_sha1, image_size)
        _copy_image(compressed, f_copy, f_bmap1, image_sha1, None)

    #
    # Pass 5: copy without bmap and make sure it is identical to the original
    # file.

    _copy_image(f_image, f_copy, None, image_sha1, image_size)
    _copy_image(f_image, f_copy, None, image_sha1, None)

    #
    # Pass 6: test compressed files copying without bmap
    #

    for compressed in _generate_compressed_files(f_image, delete = delete):
        _copy_image(compressed, f_copy, f_bmap1, image_sha1, image_size)

        # Test without setting the size
        _copy_image(compressed, f_copy, f_bmap1, image_sha1, None)

        # Append a "file:" prefixe to make BmapCopy use urllib
        _copy_image(compressed, f_copy, f_bmap1, image_sha1, image_size)
        _copy_image(compressed, f_copy, f_bmap1, image_sha1, None)

    # Close temporary files, which will also remove them
    f_copy.close()
    f_bmap1.close()
    f_bmap2.close()

class TestCreateCopy(unittest.TestCase):
    """ The test class for this unit tests. Basically executes the '_do_test()'
    function for different sparse files. """

    @staticmethod
    def test():
        """ The test entry point. Executes the '_do_test()' function for files
        of different sizes, holes distribution and format. """

        # Delete all the test-related temporary files automatically
        delete = True
        # Create all the test-related temporary files in the default directory
        # (usually /tmp).
        directory = None

        iterator = tests.helpers.generate_test_files(delete = delete,
                                                     directory = directory)
        for f_image, image_size, _, _ in iterator:
            assert image_size == os.path.getsize(f_image.name)
            _do_test(f_image, image_size, delete = delete)
