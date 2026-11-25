import pytest

pytest.importorskip("PIL")
np = pytest.importorskip("numpy")
pytest.importorskip("scipy")

from PIL import Image, ImageDraw

from tools.art import splice


def master_sprite():
    src = Image.new("RGBA", (170, 130))
    pen = ImageDraw.Draw(src)
    pen.ellipse((22, 28, 106, 82), fill="tan", outline="black", width=4)
    pen.rounded_rectangle((95, 14, 145, 70), radius=12, fill="orange", outline="black", width=3)
    pen.ellipse((119, 30, 131, 42), fill="black")
    pen.point((124, 34), fill="white")
    pen.rectangle((33, 74, 44, 113), fill="tan")
    pen.rectangle((84, 76, 94, 113), fill="tan")
    return src


def translate(image, dx, dy):
    result = Image.new("RGBA", image.size)
    result.paste(image, (dx, dy))
    return result


def test_blink_recovers_shift_and_preserves_exact_bytes_outside_disc():
    master = master_sprite()
    edit = master.copy()
    pen = ImageDraw.Draw(edit)
    pen.ellipse((118, 29, 132, 43), fill="orange")
    pen.line((119, 36, 131, 36), fill="black", width=2)
    pen.rectangle((35, 83, 44, 93), fill="purple")  # edit wandered elsewhere
    shifted = translate(edit, 8, -5)
    result, shift, residual, origin = splice.splice(master, shifted, "blink", (125, 36), 7)
    assert np.max(np.abs(np.asarray(shift) - (-8, 5))) <= 1
    assert residual == 0 and origin == (0, 0)
    y, x = np.ogrid[:master.height, :master.width]
    disc = (x - 125)**2 + (y - 36)**2 <= (1.6 * 7)**2
    expected = np.where(disc[:, :, None], np.asarray(edit), np.asarray(master))
    assert np.array_equal(result, expected)
    assert not np.array_equal(result, master)
    auto, *_ = splice.splice(master, shifted, "blink", (125, 36))
    assert auto.getpixel((125, 32)) == edit.getpixel((125, 32))


def test_step_alignment_ignores_changed_lower_bbox_and_feathers_12_pixels():
    master = master_sprite()
    edit = master.copy()
    pen = ImageDraw.Draw(edit)
    pen.rectangle((0, 70, 135, 116), fill=(60, 180, 80))
    shifted = translate(edit, 5, 7)
    result, shift, residual, _ = splice.splice(master, shifted, "step")
    assert shift == (-5, -7) and residual == 0
    seam = 14 + round(0.55 * 100)
    assert np.array_equal(np.asarray(result)[:seam + 1], np.asarray(master)[:seam + 1])
    assert np.array_equal(np.asarray(result)[seam + 12:], np.asarray(edit)[seam + 12:])
    a, b = (np.asarray(im.getpixel((39, seam + 6))) for im in (master, edit))
    assert np.max(np.abs(np.asarray(result.getpixel((39, seam + 6))) - (a + b) / 2)) <= 1


def test_rejects_five_percent_nonrigid_upper_body_residual_without_writing(tmp_path):
    master = Image.new("RGBA", (160, 120))
    draw = ImageDraw.Draw(master)
    # Two groups of landmarks of comparable length. The feet fix the 100 px height.
    for x in (20, 40, 60, 85, 105, 125):
        draw.rectangle((x, 10, x + 5, 62), fill="white")
    draw.rectangle((20, 63, 130, 109), fill="tan")
    edit = master.copy()
    movable = master.crop((76, 5, 148, 63))
    ImageDraw.Draw(edit).rectangle((76, 5, 148, 62), fill=(0, 0, 0, 0))
    edit.paste(movable, (81, 5))  # half of the upper body drifted by 5 px / 100 px
    master.save(tmp_path / "master.png")
    edit.save(tmp_path / "edit.png")
    with pytest.raises(ValueError, match="residual.*exceeds 2%"):
        splice.register(master, edit)
    with pytest.raises(SystemExit) as exit_info:
        splice.main([str(tmp_path / name) for name in ("master.png", "edit.png", "out.png")]
                    + ["--mode", "step"])
    assert exit_info.value.code == 1 and not (tmp_path / "out.png").exists()


def test_differently_trimmed_step_retains_extended_foot():
    master = master_sprite()
    edit = master.copy()
    ImageDraw.Draw(edit).rectangle((7, 100, 39, 108), fill="tan")
    master = master.crop(master.getchannel("A").getbbox())
    edit = edit.crop(edit.getchannel("A").getbbox())
    result, shift, residual, origin = splice.splice(master, edit, "step")
    assert shift == (-15, 0) and origin == (15, 0) and residual == 0
    assert result.size == edit.size
    assert result.getpixel((0, 90))[3] == 255


def test_featureless_upper_body_fails_closed():
    blank = Image.new("RGBA", (40, 40), "blue")
    with pytest.raises(ValueError, match="registration features|comparable edges"):
        splice.register(blank, blank)
