generate:
	rm -rf src/api/models/models src/api/.openapi-generator
	docker run --rm -v "$(PWD)":/local openapitools/openapi-generator-cli generate \
		-i /local/spec/openapi.yaml \
		-g python \
		-o /local/src/api \
		--package-name models \
		--global-property models,modelDocs=false,modelTests=false,apis=false,apiDocs=false,apiTests=false,supportingFiles=false
	python3 -c "from pathlib import Path; base=Path('src/api/models/models'); [p.write_text(p.read_text().replace('from models.models.', 'from .')) for p in base.glob('*.py')]"
