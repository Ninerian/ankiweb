from ankiweb.adapters.inbound.http_shared import templating

def test_virtual_table_macro_renders_expected_markup():
    template = templating._env.from_string(
        """
        {% from "components/virtual_table.html.jinja" import virtual_table %}
        {{ virtual_table(items_count=1000, item_height=30, id="test-vt") }}
        """
    )
    html = template.render()
    assert 'class="outer vt-outer"' in html
    assert 'id="test-vt"' in html
    assert 'data-virtual-table' in html
    assert 'data-items-count="1000"' in html
    assert 'data-item-height="30"' in html
    assert '<table class="table vt-table' in html
    assert '<thead>' in html
    assert '<tbody>' in html
    assert '/shell/static/bundles/tables.js' in html

def test_scroll_area_macro_renders_expected_markup():
    template = templating._env.from_string(
        """
        {% from "components/scroll_area.html.jinja" import scroll_area %}
        {% call scroll_area(id="test-sa", scroll_x=true, scroll_y=true, height="250px") %}
            <p>Content inside</p>
        {% endcall %}
        """
    )
    html = template.render()
    assert 'class="scroll-area-relative"' in html
    assert '--height: 250px;' in html
    assert 'id="test-sa"' in html
    assert 'data-scroll-area-wrapper' in html
    assert 'data-scroll-x="true"' in html
    assert 'data-scroll-y="true"' in html
    assert 'class="scroll-area measuring scroll-x scroll-y"' in html
    assert 'data-edge="top"' in html
    assert 'data-edge="bottom"' in html
    assert 'data-edge="left"' in html
    assert 'data-edge="right"' in html
    assert 'scroll-shadow top-0' in html
    assert 'scroll-shadow bottom-0' in html
    assert 'scroll-shadow start-0' in html
    assert 'scroll-shadow end-0' in html
    assert '<p>Content inside</p>' in html
    assert '/shell/static/bundles/tables.js' in html

def test_demos_render_cleanly_without_unresolved_syntax():
    vt_demo = templating.render("components/_demo_virtual_table.html.jinja")
    assert "demo-vt-100k" in vt_demo
    assert "100,000 Rows" in vt_demo

    sa_demo = templating.render("components/_demo_scroll_area.html.jinja")
    assert "demo-sa-vert" in sa_demo
    assert "demo-sa-horiz" in sa_demo
