# New ports collection makefile for:	hellanzb
# Date created:		Sat Sep 25 18:46:46 PDT 2004
# Whom:			Philip Jenveey <pjenvey@groovie.org>
#
# $FreeBSD$
# $Id$
#

PORTNAME=	hellanzb
PORTVERSION=	____VERSION____
CATEGORIES=	news
MASTER_SITES=	http://www.hellanzb.com/distfiles/
DISTNAME=	${PORTNAME}-${PORTVERSION}

MAINTAINER=	pjenvey@groovie.org
COMMENT?=	nzb downloader and post processor

USE_PYTHON=	yes
USE_PYDISTUTILS=yes

RUN_DEPENDS=	par2:${PORTSDIR}/archivers/par2cmdline \
		rar:${PORTSDIR}/archivers/rar \
		flac:${PORTSDIR}/audio/flac \
		mac:${PORTSDIR}/audio/mac \
		shorten:${PORTSDIR}/audio/shorten \
		${PYTHON_SITELIBDIR}/twisted:${PORTSDIR}/devel/py-twistedCore \
		${PYTHON_SITELIBDIR}/twisted/web:${PORTSDIR}/www/py-twistedWeb

post-install:

	@if [ ! -f ${LOCALBASE}/etc/hellanzb.conf ]; then \
		${ECHO} "Installing default configuration file."; \
		${INSTALL_DATA} ${WRKSRC}/etc/hellanzb.conf.sample ${LOCALBASE}/etc/hellanzb.conf; \
	fi

.include <bsd.port.mk>
