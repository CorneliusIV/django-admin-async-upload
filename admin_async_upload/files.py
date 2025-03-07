# -*- coding: utf-8 -*-
import fnmatch
import tempfile

from django.core.files import File
from django.utils.functional import cached_property

from admin_async_upload.storage import ResumableStorage


class ResumableFile(object):
    """
    Handles file saving and processing.
    It must only have access to chunk storage where it saves file chunks.
    When all chunks are uploaded it collects and merges them returning temporary file pointer
    that can be used to save the complete file to persistent storage.

    Chunk storage should preferably be some local storage to avoid traffic
    as files usually must be downloaded to server as chunks and re-uploaded as complete files.
    """

    def __init__(self, field, user, params):
        self.field = field
        self.user = user
        self.params = params
        self.chunk_suffix = "_part_"

    @cached_property
    def resumable_storage(self):
        return ResumableStorage()

    @cached_property
    def persistent_storage(self):
        return self.resumable_storage.get_persistent_storage()

    @cached_property
    def chunk_storage(self):
        return ResumableStorage().get_chunk_storage()

    @property
    def storage_filename(self):
        return self.resumable_storage.full_filename(self.filename, self.upload_to)

    @property
    def upload_to(self):
        return self.field.upload_to

    @property
    def chunk_exists(self):
        """
        Checks if the requested chunk exists.
        """
        return self.chunk_storage.exists(self.current_chunk_name) and \
               self.chunk_storage.size(self.current_chunk_name) == int(self.params.get('resumableCurrentChunkSize'))

    @property
    def chunk_names(self):
        """
        Iterates over all stored chunks.
        """
        chunks = []
        files = sorted(self.chunk_storage.listdir('')[1])
        for file in files:
            if fnmatch.fnmatch(file, '%s%s*' % (self.filename,
                                                self.chunk_suffix)):
                chunks.append(file)
        return chunks

    @property
    def current_chunk_name(self):
        # TODO: add user identifier to chunk name
        return "%s%s%s" % (
            self.filename,
            self.chunk_suffix,
            self.params.get('resumableChunkNumber').zfill(4)
        )

    def chunks(self):
        """
        Iterates over all stored chunks.
        """
        # TODO: add user identifier to chunk name
        files = sorted(self.chunk_storage.listdir('')[1])
        for file in files:
            if fnmatch.fnmatch(file, '%s%s*' % (self.filename,
                                                self.chunk_suffix)):
                yield self.chunk_storage.open(file, 'rb').read()

    def delete_chunks(self):
        [self.chunk_storage.delete(chunk) for chunk in self.chunk_names]

    @property
    def file(self):
        """
        Merges file and returns its file pointer.
        """
        if not self.is_complete:
            raise Exception('Chunk(s) still missing')
        outfile = tempfile.NamedTemporaryFile("w+b")
        for chunk in self.chunk_names:
            try:
                outfile.write(self.chunk_storage.open(chunk).read())
            except Exception:
                outfile.write(self.chunk_storage.open(chunk).read())
        return outfile

    @property
    def filename(self):
        """
        Gets the filename.
        """
        # TODO: add user identifier to chunk name
        filename = self.params.get('resumableFilename')
        if '/' in filename:
            raise Exception('Invalid filename')
        value = "%s_%s" % (self.params.get('resumableTotalSize'), filename)
        return value

    @property
    def is_complete(self):
        """
        Checks if all chunks are already stored.
        """
        return int(self.params.get('resumableTotalSize')) == self.size

    def process_chunk(self, file):
        """
        Saves chunk to chunk storage.
        """
        if self.chunk_storage.exists(self.current_chunk_name):
            self.chunk_storage.delete(self.current_chunk_name)
        self.chunk_storage.save(self.current_chunk_name, file)

    @property
    def size(self):
        """
        Gets size of all chunks combined.
        """
        size = 0
        for chunk in self.chunk_names:
            size += self.chunk_storage.size(chunk)
        return size

    def collect(self):
        actual_filename = self.persistent_storage.save(self.storage_filename, File(self.file))
        self.delete_chunks()
        return actual_filename
