from tempfile import NamedTemporaryFile
from urllib.parse import urlparse

from flask import request, render_template, redirect, url_for
from flask.ext.admin import BaseView, expose
from flask_admin import AdminIndexView, expose
from flask_paginate import Pagination, get_page_parameter
import requests

from .models import ImageModel, ImageMatchRelationship, ImageMatch
from . import forms, models
from .__main__ import get_posted_image, iqdb_url_dict, get_page_result



class HomeView(AdminIndexView):

    @expose('/', methods=('GET', 'POST'))
    def index(self):
        """Get index page."""
        page = request.args.get(get_page_parameter(), type=int, default=1)
        form = forms.ImageUploadForm()
        if form.file.data:
            print('resize:{}'.format(form.resize.data))
            with NamedTemporaryFile() as temp, NamedTemporaryFile() as thumb_temp:
                form.file.data.save(temp.name)
                posted_img = get_posted_image(
                    img_path=temp.name, resize=form.resize.data, thumb_path=thumb_temp.name)
                place = [x[1] for x in form.place.choices if x[0] == int(form.place.data)][0]
                url, im_place = iqdb_url_dict[place]
                query = posted_img.imagematchrelationship_set \
                    .select().join(ImageMatch) \
                    .where(ImageMatch.search_place == im_place)
                if not query.exists():
                    try:
                        posted_img_path = temp.name if not form.resize.data else thumb_temp.name
                        result_page = get_page_result(image=posted_img_path, url=url)
                    except requests.exceptions.ConnectionError as e:
                        log.error(str(e))
                        flash('Connection error.')
                        return redirect(request.url)
                    list(ImageMatch.get_or_create_from_page(
                        page=result_page, image=posted_img, place=im_place))
            return redirect(url_for('match_sha256', checksum=posted_img.checksum))

        item_per_page = 10
        entries = (
            ImageModel.select()
            .distinct()
            .join(ImageMatchRelationship)
            .where(ImageMatchRelationship.image)
            .order_by(ImageModel.id.desc())
        )
        paginated_entries = entries.paginate(page, item_per_page)
        if not entries.exists() and page != 1:
            abort(404)
        # pagination = Pagination(page, item_per_page, entries.count())
        return self.render(
            'iqdb_tagger/index.html', entries=paginated_entries,
            pagination=None, form=form)


class MatchView(BaseView):

    @expose('/')
    def index(self):
        return self.render('iqdb_tagger/match.html')

    @expose('/sha256-<checksum>')
    def match_sha256(checksum):
        """Get image match the checksum."""
        entry = models.ImageModel.get(models.ImageModel.checksum == checksum)
        return render_template('iqdb_tagger/match_checksum.html', entry=entry)

    @expose('/d/<pair_id>')
    def match_detail(self, pair_id):
        """Show single match pair."""
        nocache = False
        entry = ImageMatchRelationship.get(ImageMatchRelationship.id == pair_id)

        match_result = entry.match_result
        mt_rel = models.MatchTagRelationship.select().where(
            models.MatchTagRelationship.match == match_result)
        tags = [x.tag.full_name for x in mt_rel]
        filtered_hosts = ['anime-pictures.net', 'www.theanimegallery.com']

        if urlparse(match_result.link).netloc in filtered_hosts:
            log.debug(
                'URL in filtered hosts, no tag fetched', url=match_result.link)
        elif not tags or nocache:
            try:
                tags = list(get_tags_from_match_result(match_result))
                if not tags:
                    log.debug('Tags not founds', id=pair_id)
            except requests.exceptions.ConnectionError as e:
                log.error(str(e), url=match_result.link)
        return self.render('iqdb_tagger/match_single.html', entry=entry)

