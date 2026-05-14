# SPDX-FileCopyrightText: 2026 Andrew Zhang <whisper67265@outlook.com>
#
# SPDX-License-Identifier: BSL-1.0

"""QuickBook file format adapter for upstream Weblate.

Thin :class:`~weblate.formats.convert.ConvertFormat` subclass that delegates
parsing to :class:`~boost_weblate.utils.quickbook.QuickBookFile` and
reconstruction to :class:`~boost_weblate.utils.quickbook.QuickBookTranslator`.
Same control flow as ``AsciiDocFormat`` in ``weblate.formats.convert``.
"""

from __future__ import annotations

from typing import IO, TYPE_CHECKING

from django.utils.translation import gettext_lazy
from weblate.formats.convert import ConvertFormat
from weblate.formats.helpers import NamedBytesIO

from boost_weblate.utils.quickbook import QuickBookFile, QuickBookTranslator

if TYPE_CHECKING:
    from translate.storage.base import TranslationStore
    from weblate.formats.base import TranslationFormat


class QuickBookFormat(ConvertFormat):
    """QuickBook (.qbk) documentation file format."""

    # Translators: File format name
    name = gettext_lazy("QuickBook file")
    autoload = ("*.qbk",)
    format_id = "quickbook"
    monolingual = True

    def convertfile(
        self,
        storefile: IO[bytes],
        template_store: TranslationFormat | None,
    ) -> TranslationStore:
        qbkparser = QuickBookFile(inputfile=NamedBytesIO("", storefile.read()))

        duplicate_style = "msgctxt"
        if self.file_format_params.get("merge_duplicates"):
            duplicate_style = "merge"

        return self.convert_to_po(
            qbkparser, template_store, duplicate_style=duplicate_style
        )

    def save_content(self, handle: IO[bytes]) -> None:
        """Store content to file."""
        converter = QuickBookTranslator(
            inputstore=self.store, includefuzzy=True, outputthreshold=None
        )
        if self.template_store is None:
            msg = "Template store is required."
            raise TypeError(msg)
        templatename = self.template_store.storefile
        if hasattr(templatename, "name"):
            templatename = templatename.name
        with open(templatename, "rb") as templatefile:
            converter.translate(templatefile, handle)

    @staticmethod
    def mimetype() -> str:
        """Return most common mime type for format."""
        return "text/x-quickbook"

    @staticmethod
    def extension() -> str:
        """Return most common file extension for format."""
        return "qbk"
