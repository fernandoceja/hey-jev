"""Click-only REA mode registry shared by all Quick Command surfaces."""
MODES = (
    ('rea_research', 'Research', 'magnifyingglass'),
    ('rea_review', 'Review', 'doc.text.magnifyingglass'),
    ('rea_replicate', 'Replicate Plan', 'list.bullet.rectangle'),
    ('rea_send_builder', 'Send to Builder', 'hammer'),
)
KINDS = tuple(mode[0] for mode in MODES) + ('rea_study', 'rea_cancel')


def menu(running=False):
    items = [dict(id=id_, kind=id_, title=title, symbol=symbol, phrase='', key='')
             for id_, title, symbol in MODES]
    if running:
        items.append(dict(id='rea_cancel', kind='rea_cancel', title='Cancel REA',
                          symbol='stop.circle', phrase='', key=''))
    return dict(id='rea', title='REA', kind='submenu', symbol='magnifyingglass', items=tuple(items))
