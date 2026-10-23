"""Compile checked-in gettext catalogs without installing GNU gettext on Windows."""
from pathlib import Path

import polib


def main():
    root = Path(__file__).resolve().parents[1]
    for path in sorted((root / 'locale').glob('*/LC_MESSAGES/*.po')):
        catalog = polib.pofile(str(path))
        if catalog.untranslated_entries() or catalog.fuzzy_entries():
            raise SystemExit(f'Complete and review all translations first: {path.relative_to(root)}')
        catalog.save_as_mofile(str(path.with_suffix('.mo')))
        print(f'{path.relative_to(root)}: {len(catalog)} translated messages')


if __name__ == '__main__':
    main()
