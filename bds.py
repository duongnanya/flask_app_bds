import filetype
import os
from flask import (
    Blueprint,
    app,
    current_app,
    flash,
    jsonify,
    render_template,
    redirect,
    request,
    url_for,
    session,
)
from sqlalchemy import and_, func
from werkzeug.utils import secure_filename
from flask_login import current_user, login_required
from common import get_top_bds_24
from models import (
    Bds,
    BdsImage,
    BdsTypeRelation,
    BdsUserRelation,
    City,
    # Direction,
    Image,
    Province,
    Type,
    db,
    PriceRange,
    AreaRange,
    BdsViewCount,
)
from config import Config
from decorators import *
from PIL import Image as PILImage, ImageDraw, ImageFont
from datetime import datetime, timedelta

bds_bp = Blueprint("bds", __name__)


@bds_bp.route("/bds_list", methods=["GET", "POST"])
def bds_list():
    if user_is_auth():
        if user_is_admin_editor():
            if request.method == "POST":
                search_keyword = request.form.get("search_keyword")
                exact_search = request.form.get("exact_search") is not None

                query = Bds.query.filter_by(del_flg=False)

                if search_keyword:
                    if exact_search:
                        query = query.filter(
                            Bds.title.ilike(f"%{search_keyword}%")
                            | Bds.content.ilike(f"%{search_keyword}%")
                            | Bds.address.ilike(f"%{search_keyword}%")
                        )
                        bds_data = get_bds_data(query)
                    else:
                        bds_data = []
                        sub_keywords = search_keyword.split()
                        for i in range(len(sub_keywords), 0, -1):
                            for j in range(0, len(sub_keywords) - i + 1):
                                sub_keyword = " ".join(sub_keywords[j : j + i])
                                query = Bds.query.filter_by(del_flg=False).filter(
                                    Bds.title.ilike(f"%{sub_keyword}%")
                                    | Bds.content.ilike(f"%{sub_keyword}%")
                                    | Bds.address.ilike(f"%{sub_keyword}%")
                                )
                                bds_data.extend(get_bds_data(query))

                        # Lọc ra những BDS không bị trùng
                        bds_data = list(
                            {bds["bds"].id: bds for bds in bds_data}.values()
                        )

                        # Sắp xếp kết quả theo độ chính xác giảm dần
                        bds_data = sorted(
                            bds_data,
                            key=lambda x: -len(x["bds"].title.split())
                            + -len(x["bds"].content.split())
                            + -len(x["bds"].address.split()),
                        )

                else:
                    bds_data = get_bds_data(query)

                return render_template(
                    "bds-list.html",
                    bds_data=bds_data,
                    search_keyword=search_keyword,
                    exact_search=exact_search,
                )
            else:
                # Xử lý logic hiển thị danh sách BĐS
                bdses = Bds.query.filter_by(del_flg=False).order_by(Bds.id.asc()).all()
                bds_data = get_bds_data(bdses)
                return render_template("bds-list.html", bds_data=bds_data)
        else:
            # Hiển thị trang outside nếu Role = User
            return redirect(url_for("bds.os_bds_list"))
    else:
        flash(Config.MSG_LOGIN_REQUIRED)
        return redirect(url_for("login"))


@bds_bp.route("/bds_detail/<int:bds_id>")
def bds_detail(bds_id):
    bds = get_bds_by_id(bds_id)

    # Tìm các ảnh thuộc về BDS hiện tại
    bds_images = (
        BdsImage.query.filter_by(bds_id=bds.id, del_flg=False).all() if bds else []
    )

    # Kiểm tra số lượng ảnh để xác định số lượng ảnh còn lại
    num_images = len(bds_images)
    remaining_images = max(0, num_images - Config.IMG_QUANTITY)

    # Lấy thông tin Type
    bds_types = (
        Type.query.join(BdsTypeRelation)
        .filter(
            BdsTypeRelation.bds_id == bds.id,
            BdsTypeRelation.del_flg == False,
            Type.del_flg == False,
        )
        .all()
    )

    # Lấy thông tin City
    bds_city = City.query.get(bds.city_id)
    formatted_city_name = (
        bds_city.name.replace('Huyện', 'H.')
                    .replace('Thị xã', 'Tx.')
                    .replace('Quận', 'Q.')
                    .replace('Thành phố', 'Tp.')
    )

    # Lấy thông tin Province
    bds_province = Province.query.get(bds.province_id)
    formatted_province_name = bds_province.name.replace('Thành phố', 'Tp.')

    is_favorite = False
    user_ip = request.remote_addr  # Lấy địa chỉ IP người dùng

    # Xử lý đếm lượt truy cập
    now = datetime.now()
    view_count = BdsViewCount.query.filter(
        and_(BdsViewCount.bds_id == bds_id, BdsViewCount.view_by_user_ip == user_ip)
    ).first()

    if not view_count:
        view_count = BdsViewCount(bds_id, user_ip)
        db.session.add(view_count)
    else:
        # Kiểm tra khoảng cách thời gian giữa các lần truy cập
        min_time_diff = timedelta(minutes=Config.MIN_TIME_DIFF)
        if view_count.last_view_today and now - view_count.last_view_today < min_time_diff:
            # Nếu lần truy cập này cách lần truy cập trước ít hơn 3 phút, không tăng số lượt xem
            pass
        else:
            if view_count.last_view_today and view_count.last_view_today.date() == now.date():
                view_count.cnt_view_today += 1
            else:
                view_count.cnt_view_today = 1

            if view_count.last_view_24 and now - view_count.last_view_24 <= timedelta(hours=24):
                view_count.cnt_view_24 += 1
            else:
                view_count.cnt_view_24 = 1

            if view_count.last_view_7 and now - view_count.last_view_7 <= timedelta(days=7):
                view_count.cnt_view_7 += 1
            else:
                view_count.cnt_view_7 = 1

            if view_count.last_view_30 and now - view_count.last_view_30 <= timedelta(days=30):
                view_count.cnt_view_30 += 1
            else:
                view_count.cnt_view_30 = 1

            # Cập nhật thời gian truy cập cuối cùng
            view_count.last_view_today = now
            view_count.last_view_24 = now
            view_count.last_view_7 = now
            view_count.last_view_30 = now

    db.session.commit()

    if user_is_auth():
        is_favorite = (
            BdsUserRelation.query.filter_by(
                user_id=current_user.id, bds_id=bds.id, del_flg=False
            ).first()
            is not None
        )
        if user_is_admin_editor():
            # Hiển thị trang bds-detail.html cho admin/editor
            return render_template(
                "bds-detail.html",
                bds_images=bds_images,
                bds=bds,
                bds_types=bds_types,
                bds_city=formatted_city_name,
                bds_province=formatted_province_name,
                is_favorite=is_favorite,
                remaining_images=remaining_images,
            )

    # Hiển thị trang os-bds-detail.html nếu chưa đăng nhập hoặc Role = User
    return render_template(
        "outside/os-bds-detail.html",
        bds_images=bds_images,
        bds=bds,
        bds_types=bds_types,
        bds_city=formatted_city_name,
        bds_province=formatted_province_name,
        address=bds.address,
        price_from=format_currency(bds.price_from),
        price_to=format_currency(bds.price_to),
        is_favorite=is_favorite,
        remaining_images=remaining_images,
    )


@bds_bp.route("/bds_add_edit", methods=["GET", "POST"])
@login_required
@admin_editor_required
def bds_add_edit():
    bds_id = request.args.get("bds_id")
    bds = get_bds_by_id(bds_id) if bds_id else None

    types = Type.query.all()
    provinces = Province.query.all()
    cities = City.query.filter_by(province_id=bds.province_id).all() if bds else []
    # directions = Direction.query.all()

    # Tìm các ảnh thuộc về BDS hiện tại
    bds_images = (
        BdsImage.query.filter_by(bds_id=bds.id, del_flg=False).all() if bds else []
    )

    if request.method == "POST":
        # Lấy dữ liệu từ form
        title = request.form.get("title")
        content = request.form.get("content")
        type_ids = request.form.getlist("type-id[]")
        province_id = request.form.get("province-hidden")
        city_id = request.form.get("city-hidden")
        # direction_id = request.form.get("direction-id")
        address = request.form.get("address")
        price_from = float(request.form.get("price-from"))
        price_to = float(request.form.get("price-to"))
        area = float(request.form.get("area"))
        sold_flg = True if request.form.get("sold-flg") == "1" else False
        published_flg = True if request.form.get("published-flg") == "1" else False

        if bds:
            # Cập nhật thông tin BDS
            bds.title = title
            bds.content = content
            bds.province_id = province_id
            bds.city_id = city_id
            # bds.direction_id = direction_id
            bds.address = address
            bds.price_from = price_from
            bds.price_to = price_to
            bds.area = area
            bds.sold_flg = sold_flg
            bds.published_flg = published_flg
            bds.update_user_id = current_user.id
            db.session.add(bds)
            db.session.flush()  # Lưu BDS để có ID

            # Cập nhật các mối liên kết giữa BĐS và loại BĐS
            for bds_type_relation in bds.bds_type_relations:
                bds_type_relation.del_flg = True
                db.session.add(bds_type_relation)
            db.session.commit()

            # Tạo mới các mối liên kết giữa BĐS và loại BĐS
            for type_id in type_ids:
                bds_type_relation = BdsTypeRelation(
                    bds_id=bds.id,
                    type_id=type_id,
                    create_user_id=current_user.id,
                    update_user_id=current_user.id,
                )
                db.session.add(bds_type_relation)
            db.session.commit()
        else:
            # Tạo BDS mới
            new_bds = Bds(
                title=title,
                content=content,
                province_id=province_id,
                city_id=city_id,
                # direction_id=direction_id,
                address=address,
                price_from=price_from,
                price_to=price_to,
                area=area,
                sold_flg=sold_flg,
                published_flg=published_flg,
                create_user_id=current_user.id,
                update_user_id=current_user.id,
            )
            db.session.add(new_bds)
            db.session.flush()  # Lưu BDS để có ID

            # Thêm các loại BĐS mới
            for type_id in type_ids:
                bds_type_relation = BdsTypeRelation(
                    bds_id=new_bds.id,
                    type_id=type_id,
                    create_user_id=current_user.id,
                    update_user_id=current_user.id,
                )
                db.session.add(bds_type_relation)

        # Xử lý ảnh
        images = request.files.getlist("input2[]")
        image_ids = []
        for image in images:
            if image.filename:
                filename = secure_filename(image.filename)
                image_path = os.path.join(
                    current_app.root_path, Config.UPLOAD_FOLDER, filename
                )

                # Tạo thư mục 'static/uploads' nếu chưa tồn tại
                upload_folder = os.path.join(
                    current_app.root_path, Config.UPLOAD_FOLDER
                )
                if not os.path.exists(upload_folder):
                    os.makedirs(upload_folder)

                image.save(image_path)

                # Thêm watermark vào ảnh
                add_watermark(image_path, "Mecland.vn")

                img = Image(
                    filename=filename,
                    create_user_id=current_user.id,
                    update_user_id=current_user.id,
                )
                db.session.add(img)
                db.session.flush()  # Lưu ảnh để có ID
                image_ids.append(img.id)

        # Liên kết ảnh với BDS
        for img_id in image_ids:
            bdsImg = BdsImage(
                bds_id=bds.id,
                img_id=img_id,
                create_user_id=current_user.id,
                update_user_id=current_user.id,
            )
            db.session.add(bdsImg)

        # Xử lý xóa ảnh
        delete_image_ids = request.form.getlist("delete_images[]")
        if delete_image_ids:
            for image_id in delete_image_ids:
                bdsImage = BdsImage.query.get(int(image_id))
                if bdsImage:
                    # Xóa ảnh ở bảng Image
                    image = Image.query.get(bdsImage.img_id)
                    if image:
                        image.del_flg = True
                    # Đánh dấu xóa ảnh ở bảng BdsImage
                    bdsImage.del_flg = True
                    db.session.add(bdsImage)

        db.session.commit()
        return redirect(url_for("bds.bds_list"))

    # Trả về template bds-add-edit.html với các dữ liệu cần thiết
    return render_template(
        "bds-add-edit.html",
        bds=bds,
        bds_images=bds_images,
        types=types,
        provinces=provinces,
        cities=cities,
        # directions=directions,
        selected_province_id=bds.province_id if bds else None,
        selected_city_id=bds.city_id if bds else None,
    )


@bds_bp.route("/bds_delete/<int:bds_id>")
@login_required
@admin_editor_required
def bds_delete(bds_id):
    bds = get_bds_by_id(bds_id)
    if bds:
        # Xóa các BdsTypeRelation liên quan đến BĐS này
        BdsTypeRelation.query.filter_by(bds_id=bds.id, del_flg=False).update(
            {BdsTypeRelation.del_flg: True}
        )

        # Xóa các ảnh liên quan trong BdsImage
        BdsImage.query.filter_by(bds_id=bds.id, del_flg=False).update(
            {BdsImage.del_flg: True}
        )

        # Xóa các liên kết trong BdsUserRelation
        BdsUserRelation.query.filter_by(bds_id=bds.id, del_flg=False).update(
            {BdsUserRelation.del_flg: True}
        )

        db.session.commit()

        # Đánh dấu BĐS là đã xóa
        bds.del_flg = True
        db.session.commit()
    return redirect(url_for("bds.bds_list"))


@bds_bp.route("/os_bds_list", methods=["GET", "POST"])
def os_bds_list():
    # Initialize query and data
    query = Bds.query.filter_by(published_flg=True, del_flg=False).order_by(Bds.update_dt.desc())
    bds_data = None
    bds_type_ids = []
    bds_province_id = None
    bds_city_id = None
    price_range_id = None
    area_range_id = None
    keyword_input = ""

    # Handle POST request (filtering)
    if request.method == "POST":
        bds_type_ids = request.form.getlist("type-id[]")
        bds_province_id = request.form.get("province-hidden")
        bds_city_id = request.form.get("city-hidden")
        price_range_id = request.form.get("price-range-hidden")
        area_range_id = request.form.get("area-range-hidden")
        keyword_input = request.form.get("keyword-input")

        # Chuyển đổi bds_province_id và bds_city_id thành số nguyên
        if bds_province_id:
            bds_province_id = int(bds_province_id) if bds_province_id != 'None' else 0
        if bds_city_id:
            bds_city_id = int(bds_city_id) if bds_city_id != 'None' else 0
        if price_range_id:
            price_range_id = int(price_range_id) if price_range_id != 'None' else 0
        if area_range_id:
            area_range_id = int(area_range_id) if area_range_id != 'None' else 0

        # Apply filters to the query
        if bds_type_ids:
            bds_ids = (
                db.session.query(BdsTypeRelation.bds_id)
                .filter(BdsTypeRelation.type_id.in_(bds_type_ids))
                .filter(BdsTypeRelation.del_flg == False)
                .group_by(BdsTypeRelation.bds_id)
                .having(func.count(BdsTypeRelation.bds_id) == len(bds_type_ids))
                .all()
            )
            query = query.filter(Bds.id.in_([bds_id[0] for bds_id in bds_ids]))
        if bds_province_id:
            query = query.filter(Bds.province_id == bds_province_id)
        if bds_city_id:
            query = query.filter(Bds.city_id == bds_city_id)
        if price_range_id:
            pr = PriceRange.query.get(price_range_id)
            query = query.filter(
                Bds.price_to >= pr.price_from, Bds.price_to <= pr.price_to
            )
        if area_range_id:
            ar = AreaRange.query.get(area_range_id)
            query = query.filter(Bds.area >= ar.area_from, Bds.area <= ar.area_to)

    # Paginate results
    page = request.args.get('page', 1, type=int)
    pagination = query.paginate(page=page, per_page=Config.PER_PAGE, error_out=False)
    bds_data = get_bds_data(pagination.items)

    # Calculate start and end indices for the current page
    start_index = (pagination.page - 1) * pagination.per_page + 1
    end_index = min(pagination.page * pagination.per_page, pagination.total)

    # Fetch other data for the template
    types = Type.query.all()
    provinces = Province.query.all()
    cities = get_cities_for_template(bds_province_id)
    priceRanges = PriceRange.query.all()
    areaRanges = AreaRange.query.all()
    top_bds_24 = get_bds_data(get_top_bds_24())
    
    # Sắp xếp theo số lượt xem giảm dần
    top_bds_24_sorted = sorted(top_bds_24, key=lambda x: x['views'], reverse=True)

    # Render the template
    return render_template(
        "outside/os-bds-list.html",
        bds_data=bds_data,
        types=types,
        selected_type_ids=bds_type_ids or [],
        provinces=provinces,
        selected_province_id=bds_province_id,
        cities=cities,
        selected_city_id=bds_city_id,
        priceRanges=priceRanges,
        selected_price_range_id=price_range_id,
        areaRanges=areaRanges,
        selected_area_range_id=area_range_id,
        keyword_input=keyword_input,
        top_bds_24=top_bds_24_sorted,
        pagination=pagination,
        start_index=start_index,
        end_index=end_index,
        is_reloaded=True
    )


def get_bds_by_id(bds_id):
    bds = Bds.query.filter_by(id=bds_id, del_flg=False).first()
    return bds


# UPLOAD: validate_image
def validate_image(stream):
    kind = filetype.guess(stream)
    if kind is not None and kind.extension in ["jpg", "jpeg", "png", "gif", "bmp"]:
        return "." + kind.extension
    return None


@bds_bp.route("/get_cities/<int:province_id>", methods=["GET"])
def get_cities(province_id):
    return jsonify(get_cities_for_template(province_id))


def get_cities_for_template(province_id):
    cities = City.query.filter_by(province_id=province_id).all()
    formatted_cities = [
        {
            "id": city.id,
            "name": city.name.replace('Huyện', 'H.')
                             .replace('Thị xã', 'Tx.')
                             .replace('Quận', 'Q.')
                             .replace('Thành phố', 'Tp.')
        }
        for city in cities
    ]
    return formatted_cities


def get_bds_data(query):
    bds_data = []
    for bds in query:
        first_image = BdsImage.query.filter_by(bds_id=bds.id, del_flg=False).first()
        if first_image:
            image = Image.query.filter_by(id=first_image.img_id, del_flg=False).first()
            first_image_url = url_for("static", filename=f"uploads/{image.filename}")
        else:
            first_image_url = None

        remaining_images_count = (
            BdsImage.query.filter_by(bds_id=bds.id, del_flg=False).count() - 1
        )

        # Lấy thông tin về các loại BĐS
        bds_types = (
            Type.query.join(BdsTypeRelation)
            .filter(
                BdsTypeRelation.bds_id == bds.id,
                BdsTypeRelation.del_flg == False,
                Type.del_flg == False,
            )
            .all()
        )

        bds_city = City.query.get(bds.city_id)
        bds_province = Province.query.get(bds.province_id)

        # Áp dụng replace trên tên thành phố và tên tỉnh
        formatted_city_name = (
            bds_city.name.replace('Huyện', 'H.')
                        .replace('Thị xã', 'Tx.')
                        .replace('Quận', 'Q.')
                        .replace('Thành phố', 'Tp.')
        )
        formatted_province_name = bds_province.name.replace('Thành phố', 'Tp.')

        if user_is_auth():
            is_favorite = (
                BdsUserRelation.query.filter_by(
                    user_id=current_user.id, bds_id=bds.id, del_flg=False
                ).first()
                is not None
            )
        else:
            is_favorite = False

        # Lấy tổng số lượt xem của bds
        view_count = db.session.query(
            func.sum(BdsViewCount.cnt_view_today + BdsViewCount.cnt_view_24 + BdsViewCount.cnt_view_7 + BdsViewCount.cnt_view_30)
        ).filter(BdsViewCount.bds_id == bds.id, BdsViewCount.del_flg == False).scalar() or 0

        bds_data.append(
            {
                "bds": bds,
                "first_image_url": first_image_url,
                "remaining_images_count": remaining_images_count,
                "bds_types": bds_types,
                "bds_city": formatted_city_name,
                "bds_province": formatted_province_name,
                "address": bds.address,
                "price_from": format_currency(bds.price_from),
                "price_to": format_currency(bds.price_to),
                "is_favorite": is_favorite,
                "views": view_count,  # Thêm thông tin số lượt xem
            }
        )
    return bds_data


def format_currency(value):
    if value >= 1000000000:
        return f"{value / 1000000000:.1f} tỷ"
    elif value >= 1000000:
        decimal_part = value % 1000000 / 1000000
        if decimal_part > 0:
            return f"{value / 1000000:.1f} triệu"
        else:
            return f"{value // 1000000} triệu"
    elif value >= 1000:
        decimal_part = value % 1000 / 1000
        if decimal_part > 0:
            return f"{value / 1000:.1f} nghìn"
        else:
            return f"{value // 1000} nghìn"
    else:
        return str(int(value))


# lưu/xóa yêu thích Bds
@bds_bp.route("/toggle_favorite/<int:bds_id>", methods=["POST"])
@login_required
def toggle_favorite(bds_id):
    bds_relation = BdsUserRelation.query.filter_by(
        user_id=current_user.id, bds_id=bds_id, del_flg=False
    ).first()

    if bds_relation:
        bds_relation.del_flg = True
        db.session.add(bds_relation)
        db.session.commit()
        return jsonify({"success": True, "is_favorite": False})
    else:
        new_relation = BdsUserRelation(
            user_id=current_user.id,
            bds_id=bds_id,
            create_user_id=current_user.id,
            update_user_id=current_user.id,
        )
        db.session.add(new_relation)
        db.session.commit()
        return jsonify({"success": True, "is_favorite": True})


@bds_bp.route("/check_favorite/<int:bds_id>", methods=["GET"])
@login_required
def check_favorite(bds_id):
    bds_relation = BdsUserRelation.query.filter_by(
        user_id=current_user.id, bds_id=bds_id, del_flg=False
    ).first()
    return jsonify({"is_favorite": bool(bds_relation)})


def add_watermark(image_path, watermark_text):
    base_image = PILImage.open(image_path).convert("RGBA")
    width, height = base_image.size

    # Make the image editable
    txt = PILImage.new("RGBA", base_image.size, (255, 255, 255, 0))

    # Choose a font and size
    font = ImageFont.load_default()

    draw = ImageDraw.Draw(txt)

    # Calculate the original text size
    text_bbox = draw.textbbox((0, 0), watermark_text, font=font)
    text_width = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1]

    # Create a new font with scaled size (20 times larger)
    font_size = int(font.size * 20)
    try:
        font = ImageFont.truetype("arial.ttf", font_size)
    except IOError:
        font = ImageFont.load_default()

    # Calculate the new text size with the updated font
    text_bbox = draw.textbbox((0, 0), watermark_text, font=font)
    text_width = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1]

    # Position the watermark 50px from the top-left corner
    x = 50
    y = 50

    # Apply the watermark
    draw.text((x, y), watermark_text, font=font, fill=(255, 255, 255, 128))

    watermarked = PILImage.alpha_composite(base_image, txt)
    watermarked = watermarked.convert("RGB")  # Remove alpha for saving in JPEG format
    watermarked.save(image_path)


@bds_bp.route('/search_bds_keyword', methods=['GET'])
def search_bds_keyword():
    keyword = request.args.get('keyword', '').lower()
    results = []

    # Truy vấn cơ sở dữ liệu để lấy danh sách các bất động sản
    bds_list = Bds.query.filter_by(del_flg=False).all()

    for bds in bds_list:
        if keyword in bds.title.lower() or keyword in bds.content.lower() or keyword in bds.address.lower():
            # Xác định câu chứa từ khóa
            if keyword in bds.title.lower():
                sentence = bds.title
            elif keyword in bds.content.lower():
                sentence = bds.content
            else:
                sentence = bds.address

            results.append({
                'id': bds.id,
                'sentence': sentence,
                'detailUrl': url_for('bds.bds_detail', bds_id=bds.id)
            })
    
    return jsonify(results)