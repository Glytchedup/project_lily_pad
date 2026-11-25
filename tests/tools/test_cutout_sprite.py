import pytest

pytest.importorskip("PIL")
np = pytest.importorskip("numpy")
pytest.importorskip("scipy")

from PIL import Image, ImageDraw

from tools.art import cutout_sprite, sheet


KEYLINE = (42, 30, 44)
GREEN = (0, 200, 83)


def test_green_key_preserves_white_coat_and_despills_opaque_and_soft_edges():
    src = Image.new("RGB", (100, 100), GREEN)
    draw = ImageDraw.Draw(src)
    draw.rectangle((15, 10, 84, 89), fill=(42, 110, 44))
    draw.rectangle((19, 14, 80, 85), fill=KEYLINE)
    draw.rectangle((23, 18, 76, 81), fill="white")
    sprite, = cutout_sprite.cutout(src)
    data = np.asarray(sprite)
    assert sprite.mode == "RGBA"
    assert sprite.getchannel("A").getbbox() == (2, 2, sprite.width - 2, sprite.height - 2)
    assert sprite.getpixel((sprite.width // 2, sprite.height // 2)) == (255, 255, 255, 255)
    visible = data[data[:, :, 3] > 0]
    assert np.all(visible[:, 1] <= np.maximum(visible[:, 0], visible[:, 2]))


def test_tail_hole_survives_and_small_highlight_is_kept():
    src = Image.new("RGB", (100, 100), "white")
    draw = ImageDraw.Draw(src)
    draw.rectangle((10, 15, 89, 79), fill=KEYLINE)
    draw.ellipse((50, 30, 75, 55), fill="white")  # enclosed gap under raised tail
    draw.rectangle((20, 23, 22, 25), fill="white")  # 0.09% catchlight
    sprite, = cutout_sprite.cutout(src)
    assert sprite.getpixel((63 - 10 + 2, 43 - 15 + 2))[3] == 0
    assert sprite.getpixel((21 - 10 + 2, 24 - 15 + 2)) == (255, 255, 255, 255)


def test_halo_under_pond_limit_after_erode_and_decontamination():
    src = Image.new("RGB", (160, 160), "white")
    draw = ImageDraw.Draw(src)
    draw.ellipse((16, 16, 143, 143), fill=(215, 212, 214))  # baked white matte
    draw.ellipse((18, 18, 141, 141), fill=KEYLINE)
    draw.ellipse((28, 28, 131, 131), fill=(226, 182, 90))
    sprite, = cutout_sprite.cutout(src)
    data = np.asarray(sprite) / 255
    alpha = data[:, :, 3:4]
    soft = (alpha[:, :, 0] > 0.1) & (alpha[:, :, 0] < 0.9)
    assert soft.sum() > 100
    rgb = data[:, :, :3]
    luma = np.array([0.2126, 0.7152, 0.0722])
    pond = np.array([14, 26, 44]) / 255
    key_luma = (np.array(KEYLINE) / 255) @ luma
    assert (rgb[soft] @ luma).mean() <= key_luma + 0.08
    assert ((rgb * alpha + pond * (1 - alpha))[soft] @ luma).mean() <= key_luma + 0.08


def test_split_cli_orders_panels_keeps_detached_parts_and_drops_specks(tmp_path):
    src = Image.new("RGB", (260, 80), "white")
    draw = ImageDraw.Draw(src)
    colors = ["red", "blue", "purple"]
    for x, y, color in zip((8, 108, 174), (30, 12, 22), colors):
        draw.rectangle((x, y, x + 39, y + 35), fill=color)
        draw.rectangle((x + 20, y - 10, x + 26, y - 4), fill=color)  # >2% of main body
        draw.rectangle((x + 43, y, x + 45, y + 2), fill="black")
    src.save(tmp_path / "poses.png")
    out = tmp_path / "poses"
    cutout_sprite.main([str(tmp_path / "poses.png"), str(out), "--split", "3"])
    assert sorted(p.name for p in out.iterdir()) == ["item0.png", "item1.png", "item2.png"]
    for i, color in enumerate(colors):
        with Image.open(out / f"item{i}.png") as im:
            assert im.size == (44, 50)
            assert im.getpixel((12, 22)) == Image.new("RGBA", (1, 1), color).getpixel((0, 0))
            assert im.getpixel((25, 5))[3] == 255


def test_rejects_blank_and_too_few_panels():
    src = Image.new("RGB", (50, 50), "white")
    with pytest.raises(ValueError, match="0 foreground"):
        cutout_sprite.cutout(src)
    ImageDraw.Draw(src).rectangle((6, 6, 44, 44), fill="black")
    with pytest.raises(ValueError, match="1 foreground"):
        cutout_sprite.cutout(src, 3)


def test_contact_sheet_composites_same_undistorted_sprite_on_both_backgrounds(tmp_path):
    sprite = Image.new("RGBA", (20, 20))
    ImageDraw.Draw(sprite).rectangle((2, 2, 17, 17), fill=(240, 80, 0, 128))
    src = tmp_path / "fox.png"
    sprite.save(src)
    out = tmp_path / "board.png"
    sheet.main([str(tmp_path), str(out), "1", "64", "--bg", "#0E1A2C", "#808080"])
    with Image.open(out) as board:
        assert board.size == (128, 58)
        assert board.getpixel((0, 0)) == (14, 26, 44)
        assert board.getpixel((64, 0)) == (128, 128, 128)
        assert board.getpixel((32, 18)) == (127, 53, 22)
        assert board.getpixel((96, 18)) == pytest.approx((184, 104, 64), abs=1)
        assert board.getpixel((6, 18)) == (14, 26, 44)  # horizontal margin, square figure
