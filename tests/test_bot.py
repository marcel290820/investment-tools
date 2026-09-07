from investment_tools.bot import telegram_html


def test_a_fund_name_with_an_ampersand_does_not_break_the_message() -> None:
    # The bank names the funds. One called "S&P 500" would make Telegram reject
    # the whole message rather than the one line it appears on.
    assert telegram_html("! S&P 500") == "<pre>! S&amp;P 500</pre>"


def test_markup_in_a_fund_name_is_shown_not_obeyed() -> None:
    assert telegram_html("<b>x</b>") == "<pre>&lt;b&gt;x&lt;/b&gt;</pre>"


def test_quotes_survive_intact() -> None:
    # Inside <pre> they need no escaping and &#x27; would only be noise.
    assert telegram_html('the "World" fund') == '<pre>the "World" fund</pre>'
