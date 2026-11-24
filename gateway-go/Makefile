VERSION ?= dev

.PHONY: run build tidy test vet clean

run:
	go run ./cmd/gateway

build:
	CGO_ENABLED=0 go build -trimpath -ldflags "-s -w -X main.version=$(VERSION)" -o bin/gateway ./cmd/gateway

tidy:
	go mod tidy

test:
	go test ./...

vet:
	go vet ./...

clean:
	rm -rf bin
