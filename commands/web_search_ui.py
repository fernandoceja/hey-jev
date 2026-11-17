"""Native search answer panel: inert text with source links; audio only on an explicit click."""
import subprocess
import threading

from .web_search import google_url

_panels = []
_controller = None


def read_aloud(text):
    """Use the installed macOS voice. No paid TTS, audio prefetch, or automatic playback."""
    if text:
        threading.Thread(target=lambda: subprocess.run(['/usr/bin/say', '--', text], check=False),
                         name='jev-search-read', daemon=True).start()


def open_search_panel(result):
    # updateStatus_ calls this on the UI thread; importing this module never loads AppKit.
    controller = _panel_class().alloc().initWithResult_(result)
    if controller is not None:
        for previous in _panels:
            previous.panel.orderOut_(None)
        _panels[:] = [controller]


def _panel_class():
    global _controller
    if _controller is not None:
        return _controller
    import objc
    from AppKit import (NSApp, NSPanel, NSButton, NSScrollView, NSTextView, NSColor, NSFont,
                        NSMakeRect, NSBackingStoreBuffered, NSWindowStyleMaskTitled,
                        NSWindowStyleMaskClosable, NSWindowStyleMaskResizable,
                        NSFontAttributeName, NSForegroundColorAttributeName, NSLinkAttributeName)
    from Foundation import NSObject, NSAttributedString, NSMutableAttributedString, NSURL
    from AppKit import NSWorkspace

    class SearchController(NSObject):
        panel = objc.ivar()
        result = objc.ivar()
        read_text = objc.ivar()
        text_view = objc.ivar()

        def initWithResult_(self, result):
            self = objc.super(SearchController, self).init()
            if self is None:
                return None
            self.result = result
            self.read_text = ' '.join(s['text'] for s in result['sentences']) or result['notice']
            style = NSWindowStyleMaskTitled | NSWindowStyleMaskClosable | NSWindowStyleMaskResizable
            self.panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
                NSMakeRect(0, 0, 780, 690), style, NSBackingStoreBuffered, False)
            self.panel.setTitle_('Jev Search — ' + result['query'])
            self.panel.setMinSize_((540, 400))
            self.panel.setReleasedWhenClosed_(False)
            self.panel.setHidesOnDeactivate_(False)
            content = self.panel.contentView()
            scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(16, 60, 748, 614))
            scroll.setHasVerticalScroller_(True)
            scroll.setAutoresizingMask_(18)
            self.text_view = NSTextView.alloc().initWithFrame_(NSMakeRect(0, 0, 726, 614))
            self.text_view.setEditable_(False)
            self.text_view.setSelectable_(True)
            self.text_view.setMinSize_((0, 614))
            self.text_view.setMaxSize_((1000000, 1000000))
            self.text_view.textContainer().setContainerSize_((726, 1000000))
            self.text_view.textContainer().setHeightTracksTextView_(False)
            self.text_view.setVerticallyResizable_(True)
            self.text_view.setHorizontallyResizable_(False)
            self.text_view.setAutoresizingMask_(2)
            self.text_view.textContainer().setWidthTracksTextView_(True)
            self.text_view.setTextContainerInset_((12, 14))
            self.text_view.setBackgroundColor_(NSColor.textBackgroundColor())
            scroll.setDocumentView_(self.text_view)
            content.addSubview_(scroll)
            attributed = NSMutableAttributedString.alloc().init()

            def append(text, size=14, link=None, bold=False):
                attrs = {NSFontAttributeName: NSFont.boldSystemFontOfSize_(size) if bold else NSFont.systemFontOfSize_(size),
                         NSForegroundColorAttributeName: NSColor.textColor()}
                if link:
                    attrs[NSLinkAttributeName] = NSURL.URLWithString_(link)
                    attrs[NSForegroundColorAttributeName] = NSColor.linkColor()
                attributed.appendAttributedString_(NSAttributedString.alloc().initWithString_attributes_(text, attrs))

            append(result['query'] + '\n\n', 23, bold=True)
            if result['sentences']:
                for sentence in result['sentences']:
                    append(sentence['text'] + ' ', 16)
                    append('[{0}]'.format(sentence['source']), 16,
                           result['results'][sentence['source'] - 1]['url'])
                    append(' ')
                append('\n\n')
            else:
                append(result['notice'] + '\n\n', 16)
            if result['alternative']:
                alternate = result['results'][result['alternative'] - 1]
                append('Did you mean… ')
                append(alternate['title'], link=alternate['url'])
                append('?\n\n')
            append('Web results\n\n', 17, bold=True)
            if not result['results']:
                append('No results returned. You can try the same query in Google.\n')
            for index, row in enumerate(result['results'], 1):
                append('[{0}] {1}\n'.format(index, row['title']), 17, row['url'], True)
                append(row['url'] + '\n', 12, row['url'])
                snippet = ' '.join(row['snippet'].split())
                append(snippet[:190] + ('…' if len(snippet) > 190 else '') + '\n\n')
            append('Sources: DuckDuckGo and available pages. AI selects source sentences locally; check the linked sources.', 11)
            self.text_view.textStorage().setAttributedString_(attributed)
            for x, width, title, action in ((16, 150, 'Open in Google', 'google:'),
                                           (178, 130, 'Read aloud', 'read:')):
                button = NSButton.alloc().initWithFrame_(NSMakeRect(x, 16, width, 30))
                button.setTitle_(title)
                button.setBezelStyle_(1)
                button.setTarget_(self)
                button.setAction_(action)
                button.setAutoresizingMask_(32)
                content.addSubview_(button)
            self.panel.center()
            self.panel.makeKeyAndOrderFront_(None)
            NSApp.activateIgnoringOtherApps_(True)
            return self

        def google_(self, _sender):
            NSWorkspace.sharedWorkspace().openURL_(NSURL.URLWithString_(google_url(self.result['query'])))

        def read_(self, _sender):
            read_aloud(self.read_text)

    _controller = SearchController
    return _controller
